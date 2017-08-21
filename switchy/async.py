# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Async event IO machinery.
"""
import functools
import itertools
import time
import traceback
from threading import Thread, current_thread
import multiprocessing as mp
from collections import deque, OrderedDict
from . import utils
from .utils import get_event_time
from .connection import get_connection


class EventLoop(object):
    '''Event loop which processes FreeSWITCH ESL events using a background
    event loop (single thread) and one ``SWIGConnection``.
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
        self.consumers = {}  # callback chains, one for each event type
        self._sess2waiters = {}  # holds events being waited on
        self._blockers = []  # holds cached events for reuse
        self.events = OrderedDict()
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
        self.loop = loop

        # set up contained connections
        self._rx_con = get_connection(self.host, self.port, self.auth,
                                      loop=loop)

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

    def connected(self):
        '''Return a bool representing the aggregate cons status'''
        return self._rx_con.connected()

    def disconnect(self):
        '''Shutdown this event loop's bg thread and disconnect all esl sockets.

        WARNING
        -------
        This method should not be called by the event loop thread or you may
        see an indefinite block!
        '''
        if current_thread() is not self._thread and self.is_alive():
            self._stop()
            self._thread.join(timeout=1)
        else:
            # 1) bg thread was never started
            # 2) this is the bg thread which is obviously alive
            # it's one of the above so just kill con
            self._rx_con.disconnect()
        self.log.info("Disconnected event loop '{}' from '{}'".format(self._id,
                      self.host))

    def _stop(self):
        '''Stop bg thread by allowing it to fall through the
        `_listen_forever` loop.
        '''
        self._exit.set()
        # crucial check to avoid deadlock
        if current_thread() is not self._thread:
            # NOTE: if _rx_con is disconnected the bg thread should be looping
            # just collecting server discon events
            if self._rx_con.connected():  # might be waiting on recvEvent
                while self.is_alive():
                    self._rx_con.disconnect()
                    time.sleep(0.1)

    def wait(self, timeout=None):
        """Wait until the event loop thread terminates or timeout.
        """
        return self._thread.join(timeout) if self._thread else None

    def connect(self):
        '''Connect and initialize all managed ESL connections
        '''
        # don't allow other threads to connect when event loop is active
        # we must error here to avoid potential deadlock caused by
        # call to con.connect()
        if current_thread() is not self._thread and self.is_alive():
            raise utils.ConfigurationError(
                "event loop is already active, call 'disconnect' first")
        self._rx_con.connect()
        # subscribe rx for all events dictated by current handler set
        self._rx_con.subscribe(
            (ev for ev in self._handlers if ev not in self._unsub))
        self.log.info("Connected event loop '{}' to '{}'".format(self._id,
                      self.host))

    def add_handler(self, evname, handler):
        """Register an event handler for events of type `evname`.
        If a handler for `evname` already exists or if `evname` is in the
        unsubscribe list an error will be raised.
        """
        if self.is_alive():
            raise utils.ConfigurationError(
                "event loop is active, call `disconnect` first")
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
            callback = functools.partial(callback, *args, **kwargs)
        d = self.consumers.setdefault(ident, {}).setdefault(evname, deque())
        getattr(d, 'appendleft' if prepend else 'append')(callback)
        return True

    def remove_callback(self, evname, ident, callback):
        """Remove the callback object registered under
        :var:`evname` and :var:`ident`.
        """
        ev_map = self.consumers[ident]
        cbs = ev_map[evname]
        cbs.remove(callback)
        # clean up maps if now empty
        if len(cbs) == 0:
            ev_map.pop(evname)
        if len(ev_map) == 0:
            self.consumers.pop(ident)

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
        rx = self._rx_con
        if rx._sub and any(ev for ev in events if ev in rx._sub):
            rx.disconnect()
            # connects all cons which is a no-op if already connected
            self.connect()

        return popped

    def start(self):
        '''Start this event loop's in a thread and start processing
        all received events.
        '''
        if not self._rx_con.connected():
            raise utils.ConfigurationError("you must call 'connect' first")

        if self._thread is None or not self._thread.is_alive():
            self.log.debug("starting event loop thread...")
            self._thread = Thread(
                target=self._listen_forever, args=(),
                name='switchy_event_loop[{}]'.format(self.host),
            )
            self._thread.daemon = True  # die with parent
            self._thread.start()

    def _listen_forever(self):
        '''Process events until stopped
        '''
        self._running = True
        while not self._exit.is_set():
            # block waiting for next event
            e = self._rx_con.recv_event()
            # self.log.warning(get_event_time(e) - self._fs_time)
            if not e:
                self.log.error("Received empty event!?")
            else:
                evname = e.get('Event-Name')
                if evname:
                    consumed = self._process_event(e, evname)
                else:
                    self.log.warn("received unamed event '{}'?".format(e))
                # append events which are not consumed
                if not consumed:
                    # store up to the last 1k of each event type
                    self.events.setdefault(
                        evname, deque(maxlen=1000)).append((e, time.time()))
        self.log.debug("exiting event loop")
        self._rx_con.disconnect()
        self._exit.clear()  # clear event loop for next re-entry
        self._running = False

    def _process_event(self, e, evname):
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
        if handler:
            self.log.debug("handler is '{}'".format(handler))
            try:
                consumed, ret = utils.uncons(*handler(e))  # invoke handler
                # attempt to lookup a consuming client app (callbacks) by id
                model = ret[0]
                cid = model.cid if model else self.get_id(e, 'default')
                self.log.debug("consumer id is '{}'".format(cid))
                consumers = self.consumers.get(cid, False)
                if consumers and consumed:
                    cbs = consumers.get(evname, ())
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

                    # unblock `session.vars` waiters
                    if model in self._sess2waiters:
                        for var, events in self._sess2waiters[model].items():
                            if model.vars.get(var):
                                [event.set() for event in events]

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


def get_event_loop(host, port=EventLoop.PORT, auth=EventLoop.AUTH,
                   **kwargs):
    '''Event loop factory. When using python 3.5 + an ``asyncio`` based loop
    is used.
    '''
    if utils.py35:
        from .reactor import AsyncIOEventLoop
        return AsyncIOEventLoop(host, port, auth, **kwargs)
    else:
        return EventLoop(host, port, auth, **kwargs)
