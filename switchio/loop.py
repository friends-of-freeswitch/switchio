# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2017 Tyler Goodlet <tgoodlet@gmail.com>
"""
``asyncio`` based proactor loop.
"""
import logging
import itertools
import asyncio
import time
import traceback
import multiprocessing as mp
from functools import partial
from collections import deque
from threading import Thread, current_thread, get_ident
from . import utils
from .utils import get_event_time
from .connection import get_connection


@asyncio.coroutine
def just_yield():
    """A "just yield" coroutine which triggers an interation of the event loop.

    If you think this is a nightmare to understand have you asked yourself how
    this will ever work once these legacy types of generator "coroutines" are
    removed from the language?
    """
    yield


def new_event_loop():
    """Get the fastest loop available.
    """
    try:
        import uvloop
        return uvloop.new_event_loop()
    except ImportError as err:
        utils.log_to_stderr().warning(str(err))
        return asyncio.new_event_loop()


def handle_result(task, log, model):
    """Handle coroutine-task results.
    """
    try:
        task.result()
        log.debug("Completed {} for {}".format(task, model))
    except Exception:
        log.exception("{} failed with:".format(task))


class EventLoop(object):
    '''Processes ESL events using a background (thread) ``asyncio`` event loop
    and one ``aioesl`` connection.
    '''
    HOST = '127.0.0.1'
    PORT = '8021'
    AUTH = 'ClueCon'

    def __init__(self, host=HOST, port=PORT, auth=AUTH, app_id_headers=None,
                 loop=None):
        '''
        :param str host: Hostname or IP addr of the FS server
        :param str port: Port on which the FS process is listening for ESL
        :param str auth: Authentication password for connecting via ESL
        '''
        self.host = host
        self.port = port
        self.auth = auth
        self.log = utils.get_logger(utils.pstr(self))
        self._handlers = {}  # map: event-name -> func
        self._unsub = ()
        self.callbacks = {}  # callback chains, one for each event type
        self._sess2waiters = {}  # holds events being waited on
        self._blockers = []  # holds cached events for reuse
        # header name used for associating sip sessions into a 'call'
        self.app_id_headers = []
        if app_id_headers:
            self.app_id_headers = list(app_id_headers) + self.app_id_headers
            self.log.debug(
                "app lookup headers are: {}".format(self.app_id_headers))
        self._id = utils.uuid()

        # sync
        self._exit = mp.Event()  # indicate when event loop should terminate
        self._epoch = self._fs_time = 0.0

        # mockup thread
        self._thread = None
        self._running = False
        self.loop = loop  # only used in py3/asyncio

        # set up contained connections
        self._con = get_connection(self.host, self.port, self.auth,
                                   loop=loop)

        self.coroutines = {}  # coroutine chains, one for each event type
        self._entry_fut = None

    def __dir__(self):
        return utils.dirinfo(self)

    __repr__ = utils.con_repr

    ident = utils.pstr

    @property
    def epoch(self):
        '''Time first event was received from server'''
        return self._epoch

    @property
    def uptime(self):
        '''Uptime in minutes as per last received event time stamp'''
        return (self._fs_time - self._epoch) / 60.0

    def is_alive(self):
        '''Return bool indicating if event loop thread is running.
        '''
        return self._thread.is_alive() if self._thread else False

    def is_running(self):
        """Return ``bool`` indicating if event loop is waiting on events for
        processing.
        """
        return self._running

    def connected(self, **kwargs):
        '''Return a bool representing the aggregate cons status'''
        return self._con.connected(**kwargs)

    def _run_loop(self, debug):
        self.loop = loop = new_event_loop()
        loop._tid = get_ident()
        # FIXME: causes error with a thread safety check in Future.call_soon()
        # called from Future.add_done_callback() - stdlib needs a patch?
        if debug:
            loop.set_debug(debug)
            logging.getLogger('asyncio').setLevel(logging.DEBUG)
        asyncio.set_event_loop(loop)
        self.loop.run_forever()

    def _launch_bg_loop(self, debug=False):
        if self._thread is None or not self._thread.is_alive():
            self.log.debug("starting event loop thread...")
            self._thread = Thread(
                target=self._run_loop, args=(debug,),
                name='switchio_event_loop[{}]'.format(self.host),
            )
            self._thread.daemon = True  # die with parent
            self._thread.start()

    def connect(self, loop=None, timeout=3, debug=False, **conn_kwargs):
        '''Initialize underlying receive connection.
        '''
        # TODO: once we remove SWIG/py27 support this check can be removed
        if self.connected() and self.is_alive():
            raise utils.ConfigurationError(
                "event loop is already active, call 'disconnect()' first")
        elif self.connected():
                self.log.info("event loop is already connected")
                return

        if not self.is_alive():
            self._launch_bg_loop(debug=debug)
            while not self.loop:
                time.sleep(0.1)

        future = asyncio.run_coroutine_threadsafe(
            self._con.connect(block=False, loop=self.loop, **conn_kwargs),
            self.loop
        )
        future.result(3)  # pass through any timeout or conn errors

        # subscribe for events
        self._con.subscribe(
            (ev for ev in self._handlers if ev not in self._unsub))
        self.log.info("Connected event loop '{}' to '{}'".format(self._id,
                      self.host))

    def get_tasks(self, include_current=False):
        tasks = asyncio.all_tasks(self.loop)
        if not include_current:
            curr = asyncio.current_task(self.loop)
            tasks.discard(curr)
        return tuple(tasks)

    def start(self):
        '''Start this loop's listen coroutine and start processing
        all received events.
        '''
        self.log.debug("Starting event loop server")
        if not self._con.connected():
            raise utils.ConfigurationError("you must call 'connect' first")

        self._entry_fut = asyncio.run_coroutine_threadsafe(
            self._listen_forever(), loop=self.loop)

    def wait(self, timeout=None):
        """Wait until the event loop thread terminates or timeout.
        """
        return self._thread.join(timeout) if self._thread else None

    async def _listen_forever(self):
        '''Process events until stopped
        '''
        self.log.debug("starting listen loop")
        self._running = True
        while self._con.connected():
            # block waiting for next event
            e = await self._con.recv_event()
            # self.log.warning(get_event_time(e) - self._fs_time)
            if e is None:
                self.log.debug("Breaking from listen loop")
                break
            elif not e:
                self.log.error("Received empty event!?")
            else:
                evname = e.get('Event-Name')
                if evname:
                    consumed = await self._process_event(e, evname)
                    if not consumed:
                        self.log.warning("unconsumed  event '{}'?".format(e))
                else:
                    self.log.warning("received unnamed event '{}'?".format(e))

        pending = self.get_tasks()
        if pending:
            self.log.debug("Waiting on all pending tasks {}".format(pending))
            for task in pending:
                if not task.done():
                    self.log.warning("Cancelling {}".format(task))
                    task.cancel()
                    task.print_stack()

        self.log.debug("Exiting listen loop")
        self._running = False

    async def _process_event(self, e, evname):
        '''Process an ESL event by delegating to the appropriate handler
        and any succeeding callback chain. This is the core handler lookup
        routine and should be optimized for speed.

        An event is considered consumed if:
        1) the handler + callback chain returns True
        2) the handler + callback chain raises a special exception

        :param dict e: event received over esl
        :param str evname: event type/name string
        '''
        # epoch is the time when first event is received
        if self._epoch:
            self._fs_time = get_event_time(e)
        else:
            self._epoch = self._fs_time = get_event_time(e)

        consumed = False  # is this event consumed by a handler/callback
        if 'CUSTOM' in evname:
            evname = e.get('Event-Subclass')
        self.log.debug("receive event '{}'".format(evname))

        uid = e.get('Unique-ID')

        handler = self._handlers.get(evname, False)
        loop = self.loop
        if handler:
            self.log.debug("handler is '{}'".format(handler.__name__))
            try:
                consumed, ret = utils.uncons(*handler(e))  # invoke handler
                model = ret[0]

                # attempt to lookup a consuming client app (callbacks) by id
                cid = model.cid if model else self.get_id(e, 'default')
                self.log.debug("app id is '{}'".format(cid))

                if model:
                    # signal any awaiting futures
                    fut = model._futures.pop(evname, None)
                    if fut and not fut.cancelled():
                        fut.set_result(e)
                        # resume waiting coroutines...
                        # seriously guys, this is literally so stupid
                        # and confusing
                        await just_yield()

                callbacks = self.callbacks.get(cid, False)
                if callbacks and consumed:
                    cbs = callbacks.get(evname, ())
                    self.log.debug(
                        "consumer '{}' has callback {} registered for ev {}"
                        .format(cid, cbs, evname)
                    )
                    # look up the client's callback chain and run
                    # e -> handler -> cb1, cb2, ... cbN
                    # XXX assign ret on each interation in an attempt to avoid
                    # python's dynamic scope lookup
                    for cb, ret in zip(cbs, itertools.repeat(ret)):
                        try:
                            cb(*ret)
                        except Exception:
                            self.log.exception(
                                "Failed to execute callback {} for event "
                                "with uid {}".format(cb, uid)
                            )

                coroutines = self.coroutines.get(cid, False)
                if coroutines and consumed:
                    coros = coroutines.get(evname, ())
                    self.log.debug(
                        "app '{}' has coroutines {} registered for ev {}"
                        .format(cid, coros, evname)
                    )
                    # look up and schedule assigned coroutines
                    # e -> handler -> coro1, coro2, ... coroN
                    for coro in coros:
                        task = asyncio.ensure_future(coro(*ret), loop=loop)
                        task.add_done_callback(
                            partial(handle_result, log=self.log, model=model))
                        await just_yield()  # loop spin

                if model:
                    # unblock `session.vars` waiters
                    if model in self._sess2waiters:
                        for var, evs in self._sess2waiters[model].items():
                            if model.vars.get(var):
                                [event.set() for event in evs]

                    # if model is done, cancel any pending consumer coroutine-tasks
                    if model.done() and getattr(model, '_futures', None):
                        for name, fut in model._futures.items():
                            if not fut.done():
                                self.log.warning("Cancelling {} awaited {}".format(name, fut))
                                for task in model.tasks.get(fut, ()):
                                    task.print_stack()
                                fut.cancel()

            # exception raised by handler/chain on purpose?
            except utils.ESLError:
                consumed = True
                self.log.warning("Caught ESL error for event '{}':\n{}"
                                 .format(evname, traceback.format_exc()))
            except Exception:
                self.log.exception(
                    "Failed to process event {} with uid {}"
                    .format(evname, uid)
                )
            return consumed
        else:
            self.log.error("Unknown event '{}'".format(evname))

    def get_id(self, e, default=None):
        """Acquire the client/consumer (app) id for event :var:`e`
        """
        for var in self.app_id_headers:
            ident = e.get(var)
            if ident:
                self.log.debug(
                    "app id lookup using '{}' successfully returned '{}'"
                    .format(var, ident)
                )
                return ident
        return default

    def waitfor(self, sess, varname, timeout=None):
        '''Wait on a boolen variable `varname` to be set to true for
        session `sess` as read from `sess.vars['varname']`.
        This call blocks until the attr is set to `True` most usually
        by a callback.

        WARNING
        -------
        Do not call this from the event loop thread!
        '''
        # retrieve cached event/blocker if possible
        event = mp.Event() if not self._blockers else self._blockers.pop()
        waiters = self._sess2waiters.setdefault(sess, {})  # sess -> {vars: ..}
        events = waiters.setdefault(varname, [])  # var -> [events]
        events.append(event)

        def cleanup(event):
            """Dealloc events and waiter data structures.
            """
            event.clear()  # make it block for next cached use
            events.remove(event)  # event lifetime expires with this call
            self._blockers.append(event)  # cache for later use
            if not events:  # event list is now empty so delete
                waiters.pop(varname)
            if not waiters:  # no vars being waited so delete
                self._sess2waiters.pop(sess)

        # event was set faster then we could wait on it
        if sess.vars.get(varname):
            cleanup(event)
            return True

        res = event.wait(timeout=timeout)  # block
        if timeout and not res:
            raise mp.TimeoutError("'{}' was not set within '{}' seconds"
                                  .format(varname, timeout))
        cleanup(event)
        return res

    def disconnect(self, **con_kwargs):
        '''Shutdown this event loop's bg thread and disconnect all esl sockets.

        WARNING
        -------
        This method should not be called by the event loop thread or you may
        see an indefinite block!
        '''
        self.log.info(
            "Disconnecting event loop '{}' from '{}'"
            .format(self._id, self.host))
        if current_thread() is not self._thread and self.is_alive():
            self._stop()
            self._thread.join(timeout=1)
        else:
            # 1) bg thread was never started
            # 2) this is the bg thread which is obviously alive
            # it's one of the above so just kill con
            return self._con.disconnect(**con_kwargs)

    def _stop(self):
        '''Stop bg thread and event loop.
        '''
        if current_thread() is self._thread:
            self.log.warning("Stop called from event loop thread?")

        # wait on disconnect success
        self._con.disconnect()
        for _ in range(10):
            if self._con.connected():
                time.sleep(0.1)
            else:
                break
        else:
            if self._con.connected():
                raise TimeoutError("Failed to disconnect connection {}"
                                   .format(self._con))

        def trigger_exit():
            # manually signal listen-loop exit (usually stuck in polling
            # the queue for some weird reason?)
            self.loop.call_soon_threadsafe(
                self._con.protocol.event_queue.put_nowait, None)

        # trigger and wait on event processor loop to terminate
        trigger_exit()
        if self._entry_fut:
            self._entry_fut.result(10)

        pending = self.get_tasks(include_current=True)
        if pending:
            self.log.debug("Waiting on all pending tasks {}".format(pending))
            asyncio.run_coroutine_threadsafe(
                asyncio.wait(pending, loop=self.loop), loop=self.loop
                ).result(3)

            # XXX: this results in task exceptions be logged
            # a second time outside of ``handle_result()`` above
            for task in pending:
                try:
                    task.result()
                except Exception as err:
                    self.log.exception(task)

        # tear down the event loop
        self.loop.stop()
        for _ in range(10):
            if self.loop.is_running():
                trigger_exit()
                time.sleep(0.1)
            else:
                break
        else:
            if self.loop.is_running():
                raise TimeoutError("Failed to stop event loop {}"
                                   .format(self.loop))

    def add_handler(self, evname, handler):
        """Register an event handler for events of type ``evname``.
        If a handler for ``evname`` already exists or if ``evname`` is in the
        unsubscribe list an error will be raised.
        """
        if evname in self._unsub:
            raise utils.ConfigurationError(
                "'{}' events have been unsubscribed for this event loop"
                .format(evname))
        # TODO: add a force option which allows overwrite?
        if evname in self._handlers:
            raise utils.ConfigurationError(
                "handler '{}' for events of type '{}' already exists"
                .format(self._handlers[evname], evname))

        if self._con.connected() and evname not in self._con._sub:
            self._con.subscribe((evname,))
        # add handler to active map
        self._handlers[evname] = handler

    def add_callback(self, evname, ident, callback, *args, **kwargs):
        '''Register a callback for events of type `evname` to be called
        with provided args, kwargs when an event is received by this event
            loop.

        Parameters
        ----------
        evname : string
            name of mod_event event type you wish to subscribe for with the
            provided callback
        callback : callable
            callable which will be invoked when events of type evname are
            received on this event loop's rx connection
        args, kwargs : initial arguments which will be partially applied to
            callback right now
        '''
        prepend = kwargs.pop('prepend', False)
        # TODO: need to check outputs and error on signature mismatch!
        if not utils.is_callback(callback):
            return False
        if args or kwargs:
            callback = partial(callback, *args, **kwargs)
        d = self.callbacks.setdefault(ident, {}).setdefault(evname, deque())
        getattr(d, 'appendleft' if prepend else 'append')(callback)
        return True

    def remove_callback(self, evname, ident, callback):
        """Remove the callback object registered under
        :var:`evname` and :var:`ident`.
        """
        ev_map = self.callbacks[ident]
        cbs = ev_map[evname]
        cbs.remove(callback)
        # clean up maps if now empty
        if len(cbs) == 0:
            ev_map.pop(evname)
        if len(ev_map) == 0:
            self.callbacks.pop(ident)

    def unsubscribe(self, events):
        '''Unsubscribe this event loop's connection from an events of
        a cetain type.

        Parameters
        ----------
        events : string or iterable
            name of mod_event event type(s) you wish to unsubscribe from
            (FS server will not be told to send you events of this type)
        '''
        if self.connected():
            raise utils.ConfigurationError(
                "you must disconnect this event loop before unsubscribing"
                " from events"
            )
        failed = []
        popped = False
        if isinstance(events, str):
            events = (events,)
        # remove all active handlers
        for ev_name in events:
            self._unsub += (ev_name,)
            try:
                self._handlers.pop(ev_name)
                popped = True
            except KeyError:
                failed.append(ev_name)
        if failed:
            self.log.warning("no handler(s) registered for events of type "
                             "'{}'".format("', '".join(failed)))

        # reconnect rx con if already subscribed for unwanted events
        rx = self._con
        if rx._sub and any(ev for ev in events if ev in rx._sub):
            rx.disconnect()
            # connects all cons which is a no-op if already connected
            self.connect()

        return popped

    def add_coroutine(self, evname, ident, coro, *args, **kwargs):
        """Register a coroutine which will be scheduled when events
        of type ``evname`` are received.

        The coroutine will be scheduled only when the value of
        ``ident`` matches one of the ``self.app_id_headers`` values
        read from the event. This allows for triggering certain coroutines
        on specific session state/inputs.
        """
        prepend = kwargs.pop('prepend', False)
        if not asyncio.iscoroutinefunction(coro):
            return False
        if args or kwargs:
            coro = partial(coro, *args, **kwargs)
        d = self.coroutines.setdefault(ident, {}).setdefault(evname, deque())
        getattr(d, 'appendleft' if prepend else 'append')(coro)
        return True

    def remove_coroutine(self, evname, ident, coro):
        """Remove the coroutine object registered for events of type ``evname``
        app id header ``ident``.
        """
        ev_map = self.coroutines[ident]
        coros = ev_map[evname]
        coros.remove(coro)
        # clean up maps if now empty
        if len(coros) == 0:
            ev_map.pop(evname)
        if len(ev_map) == 0:
            self.coroutines.pop(ident)


def get_event_loop(host, port=EventLoop.PORT, auth=EventLoop.AUTH,
                   **kwargs):
    '''Event loop factory. When using python 3.5 + an ``asyncio`` based loop
    is used.
    '''
    return EventLoop(host, port, auth, **kwargs)
