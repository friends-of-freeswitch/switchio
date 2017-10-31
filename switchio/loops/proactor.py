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
from functools import partial
from collections import deque
from threading import Thread, current_thread, get_ident
from .reactor import EventLoop
from .. import utils
from ..utils import get_event_time


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
        utils.log_to_stderr().warn(str(err))
        return asyncio.new_event_loop()


def handle_result(task, log, model):
    """Handle coroutine-task results.
    """
    try:
        task.result()
        log.debug("Completed {}".format(task))
    except Exception:
        log.exception("{} failed with:".format(task))


class AsyncIOEventLoop(EventLoop):
    """Re-implementation of the event loop with ``asyncio`` and coroutines
    support.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.coroutines = {}  # coroutine chains, one for each event type
        self._entry_fut = None

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

    def connect(self, loop=None, timeout=3, **conn_kwargs):
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
            self._launch_bg_loop()
            while not self.loop:
                time.sleep(0.1)

        future = asyncio.run_coroutine_threadsafe(
            self._rx_con.connect(block=False, loop=self.loop, **conn_kwargs),
            self.loop
        )
        future.result()  # pass through any timeout or conn errors

        # subscribe for events
        self._rx_con.subscribe(
            (ev for ev in self._handlers if ev not in self._unsub))
        self.log.info("Connected event loop '{}' to '{}'".format(self._id,
                      self.host))

    def get_tasks(self, include_current=False):
        tasks = asyncio.Task.all_tasks(self.loop)
        if not include_current:
            curr = asyncio.Task.current_task(self.loop)
            tasks.discard(curr)
        return tuple(tasks)

    def start(self):
        '''Start this loop's listen coroutine and start processing
        all received events.
        '''
        if not self._rx_con.connected():
            raise utils.ConfigurationError("you must call 'connect' first")

        self._entry_fut = asyncio.run_coroutine_threadsafe(
            self._listen_forever(), loop=self.loop)

    async def _listen_forever(self):
        '''Process events until stopped
        '''
        self.log.debug("starting listen loop")
        self._running = True
        while self._rx_con.connected():
            # block waiting for next event
            e = await self._rx_con.recv_event()
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
                        self.log.warn("unconsumed  event '{}'?".format(e))
                else:
                    self.log.warn("received unnamed event '{}'?".format(e))

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

        :param ESL.ESLEvent e: event received over esl on self._rx_con
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
            self.log.debug("handler is '{}'".format(handler))
            try:
                consumed, ret = utils.uncons(*handler(e))  # invoke handler
                model = ret[0]

                # attempt to lookup a consuming client app (callbacks) by id
                cid = model.cid if model else self.get_id(e, 'default')
                self.log.debug("app id is '{}'".format(cid))

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
                if model:
                    # signal any awaiting futures
                    fut = model._futures.pop(evname, None)
                    if fut and not fut.cancelled():
                        fut.set_result(e)
                        # resume waiting coroutines...
                        # seriously guys, this is literally so stupid
                        # and confusing
                        await just_yield()

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

                        # unblock `session.vars` waiters
                        if model in self._sess2waiters:
                            for var, evs in self._sess2waiters[model].items():
                                if model.vars.get(var):
                                    [event.set() for event in evs]

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

    def _stop(self):
        '''Stop bg thread and event loop.
        '''
        if current_thread() is self._thread:
            self.log.warn("Stop called from event loop thread?")

        # wait on disconnect success
        self._rx_con.disconnect()
        for _ in range(10):
            if self._rx_con.connected():
                time.sleep(0.1)
            else:
                break
        else:
            if self._rx_con.connected():
                raise TimeoutError("Failed to disconnect connection {}"
                                   .format(self._rx_con))

        def trigger_exit():
            # manually signal listen-loop exit (usually stuck in polling
            # the queue for some weird reason?)
            self.loop.call_soon_threadsafe(
                self._rx_con.protocol.event_queue.put_nowait, None)

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

        if self._rx_con.connected() and evname not in self._rx_con._sub:
            self._rx_con.subscribe((evname,))
        # add handler to active map
        self._handlers[evname] = handler

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
