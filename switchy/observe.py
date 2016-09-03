# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Observer machinery.

Includes components for observing and controlling FreeSWITCH server state
through event processing and command invocation.
"""
import time
import traceback
import inspect
import itertools
import functools
import weakref
from contextlib import contextmanager
from threading import Thread, current_thread
from collections import deque, OrderedDict, Counter, namedtuple

# NOTE: the import order matters here!
from . import utils
from .utils import ConfigurationError, ESLError, APIError, get_event_time
from .models import Session, Job, Call
from .commands import build_originate_cmd
from . import marks
from .marks import handler
import multiprocessing as mp
from .connection import Connection, ConnectionError


def con_repr(self):
    """Repr with a [<connection-status>] slapped in"""
    rep = object.__repr__(self).strip('<>')
    return "<{} [{}]>".format(
        rep, "connected" if self.connected() else "disconnected")


class EventListener(object):
    '''ESL Listener which tracks FreeSWITCH state using an observer pattern.
    This implementation utilizes a background event loop (single thread)
    and one `Connection`.

    The main purpose is to enable event oriented state tracking of various
    slave process objects and call entities.
    '''
    HOST = '127.0.0.1'
    PORT = '8021'
    AUTH = 'ClueCon'

    def __init__(self, host=HOST, port=PORT, auth=AUTH,
                 session_map=None,
                 bg_jobs=None,
                 rx_con=None,
                 call_tracking_header='variable_call_uuid',
                 app_id_headers=None,
                 autorecon=30,
                 max_limit=float('inf'),
                 _tx_lock=None):
        '''
        :param str host: Hostname or IP addr of the FS engine server to listen to
        :param str port: Port on which the FS server is offering an ESL connection
        :param str auth: Authentication password for connecting via ESL
        :param str call_tracking_header:
            Name of the freeswitch variable (including the 'variable_' prefix)
            to use for associating sessions into tracked calls
            (see `_handle_create`).

            It is common to set this to an Xheader variable if attempting
            to track calls "through" an intermediary device (i.e. the first
            hop receiving requests) such as a B2BUA.

            NOTE: in order for this association mechanism to work the
            intermediary device must be configured to forward the Xheaders
            it receives.

        :param autorecon:
            Enable reconnection attempts on loss of a server connection.
            An integer value specifies the of number seconds to spend
            re-trying the connection before bailing. A bool of 'True'
            will poll indefinitely and 'False' will not poll at all.
        :type autorecon: int or bool
        '''
        self.host = host
        self.port = port
        self.auth = auth
        self.log = utils.get_logger(utils.pstr(self))
        self._sessions = session_map or OrderedDict()
        self._bg_jobs = bg_jobs or OrderedDict()
        self._calls = OrderedDict()  # maps aleg uuids to Sessions instances
        self.hangup_causes = Counter()  # record of causes by category
        self.failed_sessions = OrderedDict()  # store last 1k failed sessions
        self._handlers = self.default_handlers  # active handler set
        self._unsub = ()
        self.consumers = {}  # callback chains, one for each event type
        self._sess2waiters = {}  # holds events being waited on
        self._blockers = []  # holds cached events for reuse
        self.events = OrderedDict()
        self.sessions_per_app = Counter()
        self.autorecon = autorecon
        # header name used for associating sip sessions into a 'call'
        self.call_tracking_header = call_tracking_header
        self.app_id_headers = []
        if app_id_headers:
            self.app_id_headers = list(app_id_headers) + self.app_id_headers
            self.log.debug(
                "app lookup headers are: {}".format(self.app_id_headers))
        self.max_limit = max_limit
        self._id = utils.uuid()

        # sync
        self._exit = mp.Event()  # indicate when event loop should terminate
        self._lookup_blocker = mp.Event()  # used block event loop temporarily
        self._lookup_blocker.set()
        self._epoch = self._fs_time = 0.0

        # set up contained connections
        self._rx_con = rx_con or Connection(self.host, self.port, self.auth)
        self._tx_con = Connection(self.host, self.port, self.auth)
        self._cons = OrderedDict([('_rx_con', self._rx_con),
                                  ('_tx_con', self._tx_con)])

        # mockup thread
        self._thread = None
        self.reset()

    def __dir__(self):
        return utils.dirinfo(self)

    @property
    def default_handlers(self):
        """The map of default event handlers described by this listener
        """
        return {evname: cb for evname, cbtype, cb in marks.get_callbacks(
                self, skip=('default_handlers',), only='handler')}

    __repr__ = con_repr

    ident = utils.pstr

    @property
    def sessions(self):
        return self._sessions

    def count_sessions(self):
        return len(self.sessions)

    def count_failed(self):
        '''Return the failed session count
        '''
        return sum(
            self.hangup_causes.values()
        ) - self.hangup_causes['NORMAL_CLEARING']

    @property
    def bg_jobs(self):
        '''Background jobs collection'''
        return self._bg_jobs

    def count_jobs(self):
        return len(self.bg_jobs)

    @property
    def calls(self):
        return self._calls

    def count_calls(self):
        '''Count the number of active calls hosted by the slave process
        '''
        return len(self.calls)

    def iter_cons(self):
        '''Return an iterator over all contained ESL connections.
        '''
        return self._cons.items()

    @property
    def epoch(self):
        '''Time first event was received from server'''
        return self._epoch

    @property
    def uptime(self):
        '''Uptime in minutes as per last received event time stamp'''
        return (self._fs_time - self._epoch) / 60.0

    def block_jobs(self):
        '''Block the event loop from processing
        background job events (useful for registering for
        job events - see `self.register_job`)

        WARNING
        -------
        This will block the event loop thread permanently starting on the next
        received background job event. Be sure to run 'unblock_jobs'
        immediately after registering your job.
        '''
        self._lookup_blocker.clear()

    def unblock_jobs(self):
        '''Unblock the event loop from processing
        background job events
        '''
        self._lookup_blocker.set()

    def status(self):
        '''Return the status of ESL connections in a dict
        A value of True indicates that the connection is active.
        Returns map of con names -> connected() bools.
        '''
        return {name: con.connected() for name, con in self.iter_cons()}

    def is_alive(self):
        '''Return bool indicating if listener is running
        (i.e. the background event loop is executing).
        '''
        return self._thread.is_alive() if self._thread else False

    def reset(self):
        '''Clear all internal stats and counters
        '''
        self.log.debug('resetting all stats...')
        self.hangup_causes.clear()
        self.failed_jobs = Counter()
        self.total_answered_sessions = 0

    def start(self):
        '''Start this listener's event loop in a thread to start tracking
        the slave-server's state
        '''
        if not self._rx_con.connected():
            raise ConfigurationError("you must call 'connect' first")

        if self._thread is None or not self._thread.is_alive():
            self.log.debug("starting event loop thread...")
            self._thread = Thread(
                target=self._listen_forever, args=(),
                name='switchy_event_loop[{}]'.format(self.host),
            )
            self._thread.daemon = True  # die with parent
            self._thread.start()

    def connected(self):
        '''Return a bool representing the aggregate cons status'''
        return all(con.connected() for name, con in self.iter_cons())

    def disconnect(self):
        '''Shutdown this listener's bg thread and disconnect all esl sockets.

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
        self._tx_con.disconnect()
        self.log.info("Disconnected listener '{}' from '{}'".format(self._id,
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
        '''Connect and initialize all contained esl sockets
        (namely `self._rx_con` and `self._tx_con`)
        '''
        # don't allow other threads to connect when event loop is active
        # we must error here to avoid potential deadlock caused by
        # call to con.connect()
        if current_thread() is not self._thread and self.is_alive():
            raise ConfigurationError(
                "listener is already active, call 'disconnect' first")
        for name, con in self.iter_cons():
            con.connect()
        # subscribe rx for all events dictated by current handler set
        self._rx_con.subscribe(
            (ev for ev in self._handlers if ev not in self._unsub))
        self.log.info("Connected listener '{}' to '{}'".format(self._id,
                      self.host))

    def get_new_con(self, server=None, port=None, auth=None,
                    register_events=False,
                    **kwargs):
        '''
        Return a new esl connection to the specified FS server and optionally
        subscribe to any events actively handled by this listener

        Parameters
        ----------
        server : string
            fs server ip
        port : string
            port to connect on
        auth : string
            authorization username
        register_events : bool
            indicates whether or not the connection should be subscribed
            to receive all default events declared by the listener's
            'default_handlers' map
        kwargs : same as for .connection.Connection

        Returns
        -------
        con : Connection
        '''
        con = Connection(server or self.host, port or self.port,
                         auth or self.auth, **kwargs)
        if register_events:
            con.subscribe(self._handlers)
        return con

    def add_handler(self, evname, handler):
        """Register an event handler for events of type `evname`.
        If a handler for `evname` already exists or if `evname` is in the
        unsubscribe list an error will be raised.
        """
        if self.is_alive():
            raise ConfigurationError(
                "listener is active, call `disconnect` first")
        if evname in self._unsub:
            raise ConfigurationError(
                "'{}' events have been unsubscribed for this listener"
                .format(evname))
        # TODO: add a force option which allows overwrite?
        if evname in self._handlers:
            raise ConfigurationError(
                "handler '{}' for events of type '{}' already exists"
                .format(self._handlers[evname], evname))

        if evname not in self._rx_con._sub:
            self._rx_con.subscribe((evname,))
        # add handler to active map
        self._handlers[evname] = handler

    def add_callback(self, evname, ident, callback, *args, **kwargs):
        '''Register a callback for events of type `evname` to be called
        with provided args, kwargs when an event is received by this listener.

        Parameters
        ----------
        evname : string
            name of mod_event event type you wish to subscribe for with the
            provided callback
        callback : callable
            callable which will be invoked when events of type evname are
            received on this listener's rx connection
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
        '''Unsubscribe this listener from an events of a cetain type

        Parameters
        ----------
        events : string or iterable
            name of mod_event event type(s) you wish to unsubscribe from
            (FS server will not be told to send you events of this type)
        '''
        if self.is_alive():
            raise ConfigurationError("you must stop/disconnect this listener"
                                     " before unsubscribing from events")
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

    def register_job(self, event, **kwargs):
        '''Register for a job to be handled when the appropriate event arrives.
        Once an event corresponding to the job is received, the bgjob event
        handler will 'consume' it and invoke its callback.

        Parameters
        ----------
        event : ESL.ESLevent
            as returned from an ESLConnection.bgapi call
        kwargs : dict
            same signatures as for Job.__init__

        Returns
        -------
        bj : an instance of Job (a background job)
        '''
        bj = Job(event, **kwargs)
        self.bg_jobs[bj.uuid] = bj
        return bj

    def _listen_forever(self):
        '''Process events until stopped
        '''
        while not self._exit.is_set():
            # block waiting for next event
            e = self._rx_con.recvEvent()
            # self.log.warning(get_event_time(e) - self._fs_time)
            if not e:
                self.log.error("Received empty event!?")
            else:
                evname = e.getHeader('Event-Name')
                if evname:
                    consumed = self._process_event(e, evname)
                else:
                    self.log.warn("received unamed event '{}'?".format(e))
                # append events which are not consumed
                if not consumed:
                    # store up to the last 1k of each event type
                    self.events.setdefault(
                        evname, deque(maxlen=1000)).append((e, time.time()))
        self.log.debug("exiting listener event loop")
        self._rx_con.disconnect()
        self._exit.clear()  # clear event loop for next re-entry

    # (uncomment for profiling)
    # @profile.do_cprofile
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
            evname = e.getHeader('Event-Subclass')
        self.log.debug("receive event '{}'".format(evname))

        uid = e.getHeader('Unique-ID')

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
            except ESLError:
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
            ident = e.getHeader(var)
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

    def lookup_sess(self, e):
        """The most basic handler template which looks up the locally tracked
        session corresponding to event `e` and updates it with event data
        """
        uuid = e.getHeader('Unique-ID')
        sess = self.sessions.get(uuid, False)
        if sess:
            sess.update(e)
            return True, sess
        return False, None

    # primary event handlers

    _handle_sd = handler('SOCKET_DATA')(Connection._handle_socket_data)

    @handler('LOG')
    def _handle_log(self, e):
        self.log.info(e.getBody())
        return True, None

    @handler('SERVER_DISCONNECTED')
    def _handle_disconnect(self, e):
        """optionally poll waiting for connection to resume until timeout
        or shutdown
        """
        self.disconnect()
        self.log.warning("handling DISCONNECT from server '{}'"
                         .format(self.host))
        count = self.autorecon
        if count:
            while count:
                try:
                    self.connect()
                except ConnectionError:
                    count -= 1
                    self.log.warning("Failed reconnection attempt...retries"
                                     " left {}".format(count))
                    time.sleep(1)
                else:
                    assert self.connected()
                    assert self.is_alive()
                    return True, None
        # if we couldn't reconnect then have this thread exit
        self._exit.set()
        self.log.warning("Reconnection attempts to '{}' failed. Please call"
                         " 'connect' manually when server is ready "
                         .format(self.host))
        return True, None

    @handler('BACKGROUND_JOB')
    def _handle_bj(self, e):
        '''Handle bjs and report failures.
        If a job is found in the local cache then update the instance
        with event data.
        This handler returns 'None' on error (i.e. failed bj)
        which must be handled by any callbacks.
        '''
        error = False
        consumed = False
        resp = None
        sess = None
        ok = '+OK '
        err = '-ERR'
        job_uuid = e.getHeader('Job-UUID')
        body = e.getBody()
        # always report errors even for jobs which we aren't tracking
        if err in body:
            resp = body.strip(err).strip()
            error = True
            self.log.debug("job '{}' failed with:\n{}".format(
                           job_uuid, str(body)))

        if job_uuid in self.bg_jobs:
            job = self.bg_jobs.get(job_uuid, None)
        else:
            # might be in the middle of inserting a job
            self._lookup_blocker.wait()
            job = self.bg_jobs.get(job_uuid, None)

        # if this job is registered, process it
        if job:
            job.update(e)
            consumed = True
            # if the job returned an error, report it and remove the job
            if error:
                # if this job corresponds to a tracked session then
                # remove it as well
                if job.sess_uuid:
                    self.log.error(
                        "Job '{}' corresponding to session '{}'"
                        " failed with:\n{}".format(
                            job_uuid,
                            job.sess_uuid, str(body))
                        )
                    # session may already have been popped in hangup handler?
                    # TODO make a special method for popping sessions?
                    sess = self.sessions.pop(job.sess_uuid, None)
                    if sess:
                        # remove any call containing this session
                        call = sess.call
                        if call:
                            call = self.calls.pop(call.uuid, None)
                        else:
                            self.log.debug("No Call containing Session "
                                           "'{}'".format(sess.uuid))
                    else:
                        self.log.warn("No session corresponding to bj '{}'"
                                      .format(job_uuid))
                job.fail(resp)  # fail the job
                # always pop failed jobs
                self.bg_jobs.pop(job_uuid)
                # append the id for later lookup and discard?
                self.failed_jobs[resp] += 1

            # success, associate with any related session
            elif ok in body:
                resp = body.strip(ok + '\n')

                # special case: the bg job event returns an originated
                # session's uuid in its body
                sess = self.sessions.get(resp, None)
                if sess:
                    if job.sess_uuid:
                        assert str(job.sess_uuid) == str(resp), \
                            ("""Session uuid '{}' <-> BgJob uuid '{}' mismatch!?
                             """.format(job.sess_uuid, resp))

                    # reference this job in the corresponding session
                    # self.sessions[resp].bg_job = job
                    sess.bg_job = job
                    self.log.debug("Job '{}' was sucessful".format(
                                   job_uuid))
                # run the job's callback
                job(resp)
            else:
                self.log.warning("Received unexpected job message:\n{}"
                                 .format(body))
        return consumed, sess, job

    def _handle_initial_event(self, e):
        '''Handle channel create events by building local
        `Session` and `Call` objects for state tracking.
        '''
        uuid = e.getHeader('Unique-ID')
        # Record the newly activated session
        # TODO: pass con as weakref?
        con = self._tx_con

        # short circuit if we have already allocated a session since FS is
        # indeterminate about which event create|originate will arrive first
        sess = self.sessions.get(uuid)
        if sess:
            return True, sess

        # allocate a session model
        sess = Session(e, uuid=uuid, con=con)
        direction = sess['Call-Direction']
        self.log.debug("{} session created with uuid '{}'".format(
                       direction, uuid))
        sess.cid = self.get_id(e, 'default')

        # Use our specified "call identification variable" to try and associate
        # sessions into calls. By default the 'variable_call_uuid' channel
        # variable is used for tracking locally bridged calls
        call_uuid = e.getHeader(self.call_tracking_header)  # could be 'None'
        if not call_uuid:
            self.log.warn(
                "Unable to associate {} session '{}' with a call using "
                "variable '{}'".format(
                    direction, sess.uuid, self.call_tracking_header))
            call_uuid = uuid

        # associate sessions into a call
        # (i.e. set the relevant sessions to reference each other)
        if call_uuid in self.calls:
            call = self.calls[call_uuid]
            self.log.debug("session '{}' is bridged to call '{}'".format(
                           uuid, call.uuid))
            # append this session to the call's set
            call.append(sess)

        else:  # this sess is not yet tracked so use its id as the 'call' id
            call = Call(call_uuid, sess)
            self.calls[call_uuid] = call
            self.log.debug("call created for session '{}'".format(call_uuid))
        sess.call = call
        self.sessions[uuid] = sess
        self.sessions_per_app[sess.cid] += 1
        return True, sess

    _handle_create = handler('CHANNEL_CREATE')(_handle_initial_event)

    # The first event received is indeterminate
    _handle_originate = handler('CHANNEL_ORIGINATE')(_handle_initial_event)

    _handle_park = handler('CHANNEL_PARK')(lookup_sess)

    _handle_update = handler('CALL_UPDATE')(lookup_sess)

    @handler('CHANNEL_ANSWER')
    def _handle_answer(self, e):
        '''Handle answer events

        Returns
        -------
        sess : session instance corresponding to uuid
        '''
        uuid = e.getHeader('Unique-ID')
        sess = self.sessions.get(uuid, None)
        if sess:
            self.log.debug('answered session {} with call direction {}'
                           .format(uuid,  e.getHeader('Call-Direction')))
            sess.answered = True
            self.total_answered_sessions += 1
            sess.update(e)
            return True, sess
        else:
            self.log.warn('Skipping answer of {}'.format(uuid))
            return False, None

    @handler('CHANNEL_HANGUP')
    def _handle_hangup(self, e):
        '''Handle hangup events

        Returns
        -------
        sess : session instance corresponding to uuid
        job  : corresponding bj for a session if exists, ow None
        '''
        uuid = e.getHeader('Unique-ID')
        sess = self.sessions.pop(uuid, None)
        direction = sess['Call-Direction'] if sess else 'unknown'
        if not sess:
            return False, None
        sess.update(e)
        sess.hungup = True
        cause = e.getHeader('Hangup-Cause')
        self.hangup_causes[cause] += 1  # count session causes
        self.sessions_per_app[sess.cid] -= 1

        # if possible lookup the relevant call
        call_uuid = e.getHeader(self.call_tracking_header)
        if not call_uuid:
            self.log.warn(
                "handling HANGUP for {} session '{}' which can not be "
                "associated with an active call using {}?"
                .format(direction, sess.uuid, self.call_tracking_header))
            call_uuid = uuid

        # XXX seems like sometimes FS changes the `call_uuid`
        # between create and hangup oddly enough
        call = self.calls.get(call_uuid, sess.call)
        if call:
            if sess in call.sessions:
                self.log.debug("hungup {} session '{}' for Call '{}'".format(
                               direction, uuid, call.uuid))
                call.sessions.remove(sess)
            else:
                # session was somehow tracked by the wrong call
                self.log.err("session '{}' mismatched with call '{}'?"
                             .format(sess.uuid, call.uuid))

            # all sessions hungup
            if len(call.sessions) == 0:
                self.log.debug("all sessions for call '{}' were hung up"
                               .format(call_uuid))
                # remove call from our set
                call = self.calls.pop(call.uuid, None)
                if not call:
                    self.log.warn(
                        "Call with id '{}' containing Session '{}' was "
                        "already removed".format(call.uuid, sess.uuid))
        else:
            # we should never get hangups for calls we never saw created
            self.log.err("no call found for '{}'".format(call_uuid))

        # pop any corresponding job
        job = sess.bg_job
        # may have been popped by the partner
        self.bg_jobs.pop(job.uuid if job else None, None)
        sess.bg_job = None  # deref job - avoid mem leaks

        if not sess.answered or cause != 'NORMAL_CLEARING':
            self.log.debug("'{}' was not successful??".format(sess.uuid))
            self.failed_sessions.setdefault(
                cause, deque(maxlen=1000)).append(sess)

        self.log.debug("hungup Session '{}'".format(uuid))
        # hangups are always consumed
        return True, sess, job


class Client(object):
    '''Interface for synchronous server control using the esl "inbound method"
    as described here:
    https://wiki.freeswitch.org/wiki/Mod_event_socket#Inbound

    Provides a high level interface for interaction with an event listener.
    '''
    app_id_header = utils.xheaderify('switchy_app')

    def __init__(self, host='127.0.0.1', port='8021', auth='ClueCon',
                 call_tracking_header=None, listener=None, logger=None):

        self.host = host
        self.port = port
        self.auth = auth
        # works under the assumption that x-headers are forwarded by the proxy
        self.call_tracking_header = call_tracking_header or utils.xheaderify(
            'switchy_originating_session')

        self._id = utils.uuid()
        self._orig_cmd = None
        self.log = logger or utils.get_logger(utils.pstr(self))
        # clients can host multiple "composed" apps
        self._apps = {}
        self.apps = type('apps', (), {})()
        self.apps.__dict__ = self._apps  # dot-access to `_apps` from `apps`
        self.client = self  # for app funcarg insertion

        # WARNING: order of these next steps matters!
        # create a local connection for sending commands
        self._con = Connection(self.host, self.port, self.auth)
        # if the listener is provided it is expected that the
        # user will run the set up methods (i.e. connect, start, etc..)
        self.listener = listener

    __repr__ = con_repr

    def get_listener(self):
        if self._listener:
            return self._listener
        else:
            raise AttributeError(
                "No listener has been assigned for this client")

    def set_listener(self, inst):
        self._listener = inst
        # add our con to the listener's set so that it will be
        # managed on server disconnects
        if inst:
            self._listener.call_tracking_header = utils.param2header(
                self.call_tracking_header)
            self.log.debug("set call lookup variable to '{}'".format(
                self._listener.call_tracking_header))

    listener = property(get_listener, set_listener,
                        'Reference to the underlying EventListener')

    def get_loglevel(self):
        token, num = self.cmd(
            'fsctl loglevel').rpartition(':')[-1].split()
        num = num.strip('[]')
        return token, num

    def set_loglevel(self, value):
        self.cmd('fsctl loglevel {}'.format(value))

    loglevel = property(get_loglevel, set_loglevel)

    def load_app(self, ns, on_value=None, header=None, prepend=False,
                 funcargsmap=None, **prepost_kwargs):
        """Load annotated callbacks and from a namespace and add them
        to this client's listener's callback chain.

        :param ns: A namespace-like object containing functions marked with
            @event_callback (can be a module, class or instance).
        :params str on_value: app group id key to be used for registering app
            callbacks with the `EventListener`. This value will be inserted in
            the `originate` command as an X-header and used to look up which
            app callbacks should be invoked for each received event.
        """
        listener = self.listener
        name = utils.get_name(ns)
        group_id = on_value or name or utils.uuid()
        app_map = self._apps.get(group_id, None)
        if app_map and name in app_map and group_id != 'default':
            # only allow 1 app inst per group
            raise ConfigurationError(
                "an app instance with name '{}' already exists for app group "
                "'{}'.\nIf you want multiple instances of the same app load "
                "them using different `on_value` ids."
                .format(name, group_id)
            )

        # if handed a class, instantiate appropriately
        app = ns() if isinstance(ns, type) else ns

        # handle prepost-fixture setup/teardown
        prepost = getattr(app, 'prepost', False)
        if prepost:
            funcargsmap = funcargsmap or {}
            # deliver args declared in the function signature
            args, kwargs = utils.get_args(app.prepost)
            funcargs = []
            for argname in args:
                if argname == 'self':
                    continue
                funcargs.append(weakref.proxy(
                    funcargsmap.get(argname) or getattr(self, argname)))

            ret = prepost(*funcargs, **prepost_kwargs)
            if inspect.isgenerator(ret):
                # run init step
                next(ret)
                app._finalize = ret

        self.log.info(
            "Loading call app '{}' with group id '{}' for listener '{}'"
            .format(name, group_id, listener)
        )
        failed = False
        cb_paths = []
        # insert handlers and callbacks
        for ev_type, cb_type, obj in marks.get_callbacks(app):
            if cb_type == 'handler':
                # TODO: similar unloading on failure here as above?
                listener.add_handler(ev_type, obj)

            elif cb_type == 'callback':
                # add default handler if none exists
                if ev_type not in listener._handlers:
                    self.log.info(
                        "adding default session lookup handler for event"
                        " type '{}'".format(ev_type)
                    )
                    listener.add_handler(
                        ev_type,
                        listener.lookup_sess
                    )
                added = listener.add_callback(
                    ev_type, group_id, obj, prepend=prepend)
                if not added:
                    failed = obj
                    for path in reversed(cb_paths):
                        listener.remove_callback(*path)
                    break
                cb_paths.append((ev_type, group_id, obj))
                self.log.debug("'{}' event callback '{}' added for id '{}'"
                               .format(ev_type, obj.__name__, group_id))

        if failed:
            raise TypeError("app load failed since '{}' is not a valid"
                            "callback type".format(failed))

        # prepend the provided header to use for app id look ups
        # TODO: should probably be moved into `add_callback()`?
        header = header or utils.param2header(self.app_id_header)
        if header not in listener.app_id_headers:
            listener.app_id_headers.insert(0, header)
            self.log.debug("app id var '{}' prepended to {}"
                           .format(header, listener))

        # register locally
        self._apps.setdefault(group_id, {})[name] = app
        app.cid, app.name = group_id, name
        return group_id

    def unload_app(self, on_value, ns=None):
        """Unload all callbacks associated with a particular app
        `on_value` id.
        If `ns` is provided unload only the callbacks from that particular
        subapp.
        """
        app_map = self._apps.get(on_value)
        if app_map is None:
            self.log.debug("app for id {} was already unloaded".format(
                on_value))
            return

        appkeys = [utils.get_name(ns)] if ns else list(app_map.keys())

        for name in appkeys:
            app = app_map.pop(name)
            # run prepost teardown
            finalize = getattr(app, '_finalize', False)
            if finalize:
                try:
                    next(finalize)
                except StopIteration:
                    pass
            # remove callbacks
            for ev_type, cb_type, obj in marks.get_callbacks(app):
                # XXX we need a sane way to remove handlers as well!
                if cb_type == 'callback':
                    self.listener.remove_callback(ev_type, on_value, obj)

        if not app_map:
            self._apps.pop(on_value)

    def disconnect(self):
        """Disconnect the client's underlying connection
        """
        self._con.disconnect()
        time.sleep(0.1)

    def connect(self):
        """Connect this client
        """
        self._con.connect()
        assert self.connected(), "Failed to connect to '{}'".format(
            self.host)

    def connected(self):
        """Check if connection is active
        """
        return self._con.connected()

    def api(self, cmd, exc=True):
        '''Invoke esl api command with error checking
        Returns an ESL.ESLEvent instance for event type "SOCKET_DATA".
        '''
        # NOTE api calls do not require an active listener
        # since we can handle the event processing synchronously
        try:
            event = self._con.api(cmd)
        except APIError:
            if exc:
                raise
        return event

    def cmd(self, cmd):
        '''Return the string-body output from invoking a command
        '''
        return self._con.cmd(cmd)

    def hupall(self, group_id=None):
        """Hangup all calls associated with this client
        by iterating all managed call apps and hupall-ing
        with the apps callback id. If :var:`group_id` is provided
        look up the corresponding app an hang up calls for that
        specific app.
        """
        if not group_id:
            # hangup all calls for all apps
            for group_id in self._apps:
                self.api('hupall NORMAL_CLEARING {} {}'.format(
                         self.app_id_header, group_id))
        else:
            self.api('hupall NORMAL_CLEARING {} {}'.format(
                     self.app_id_header, group_id))

    def _assert_alive(self, listener=None):
        """Assert our listener is active and if so return it
        """
        listener = listener or self.listener
        if not listener.is_alive():
            raise ConfigurationError(
                "start this {} before issuing bgapi"
                .format(listener)
            )
        return listener

    def bgapi(self, cmd, listener=None, callback=None, client_id=None,
              **jobkwargs):
        '''Execute a non blocking api call and handle it to completion

        Parameters
        ----------
        cmd : string
            command to execute
        listener : EvenListener instance
            listener which will handle bg job events for this cmd
        callback : callable
            Object to call once the listener collects the bj event result.
            By default the listener calls back the job instance with the
            response from the 'BACKGROUND_JOB' event's body content plus any
            kwargs passed here.
        '''
        listener = self._assert_alive(listener)
        # block the event loop while we insert our job
        listener.block_jobs()
        try:
            ev = self._con.bgapi(cmd)
            if ev:
                bj = listener.register_job(
                    ev, callback=callback,
                    client_id=client_id or self._id,
                    **jobkwargs
                )
            else:
                if not self._con.connected():
                    raise ConnectionError("local connection down on '{}'!?"
                                          .format(self._con.host))
                else:
                    raise APIError("bgapi cmd failed?!\n{}".format(cmd))
        finally:
            # wakeup the listener's event loop
            listener.unblock_jobs()
        return bj

    def originate(self, dest_url=None,
                  uuid_func=utils.uuid,
                  app_id=None,
                  listener=None,
                  bgapi_kwargs={},
                  rep_fields={},
                  **orig_kwargs):
        '''Originate a call using FreeSWITCH 'originate' command.
        A non-blocking bgapi call is used by default.

        Parameters
        ----------
        see :func:`build_originate_cmd`

        orig_kwargs: additional originate cmd builder kwargs forwarded to
            :func:`build_originate_cmd` call

        Returns
        -------
        instance of `Job` a background job
        '''
        listener = self._assert_alive(listener)
        # gen originating session uuid for tracking call
        uuid_str = uuid_func()
        if dest_url:  # generate the cmd now
            origkwds = {self.app_id_header: app_id or self._id}
            origkwds.update(orig_kwargs)
            cmd_str = build_originate_cmd(
                dest_url,
                uuid_str=uuid_str,
                xheaders={self.call_tracking_header: uuid_str},
                **origkwds
            )
        else:  # accept late data insertion for the uuid_str and app_id
            cmd_str = self.originate_cmd.format(
                uuid_str=uuid_str,
                app_id=app_id or self._id,
                **rep_fields
            )

        return self.bgapi(
            cmd_str, listener,
            sess_uuid=uuid_str,
            client_id=app_id,
            **bgapi_kwargs
        )

    @functools.wraps(build_originate_cmd)
    def set_orig_cmd(self, *args, **kwargs):
        '''Build and cache an originate cmd string for later use
        as the default input for calls to `originate`
        '''
        # by default this inserts a couple placeholders which can be replaced
        # at run time by a format(uuid_str='blah', app_id='foo') call
        xhs = {}
        if self.listener:
            xhs[self.call_tracking_header] = '{uuid_str}'
        xhs.update(kwargs.pop('xheaders', {}))  # overrides from caller

        origparams = {self.app_id_header: '{app_id}'}
        if 'uuid_str' in kwargs:
            raise ConfigurationError(
                "passing 'uuid_str' here is improper usage")
        origparams.update(kwargs)

        # build a reusable command string
        self._orig_cmd = build_originate_cmd(
            *args,
            xheaders=xhs,
            **origparams
        )

    @property
    def originate_cmd(self):
        return self._orig_cmd


def get_listener(host, port=EventListener.PORT, auth=EventListener.AUTH,
                 mng=None, mng_init=None, **kwargs):
    '''Listener factory which can be used to load a local instance or a shared
    proxy using `multiprocessing.managers`
    '''
    # return a listener local to this process
    return EventListener(host, port, auth, **kwargs)


@contextmanager
def active_client(host, port='8021', auth='ClueCon',
                  apps=None):
    '''A context manager which delivers an active `Client` containing a started
    `EventListener` with applications loaded that were passed in the `apps` map
    '''
    client = Client(
        host, port, auth, listener=get_listener(host, port, auth)
    )
    client.listener.connect()
    client.connect()

    # TODO: maybe we should (try to) use the app manager here?
    # load app set
    if apps:
        if getattr(apps, 'items', None):
            apps = apps.items()

        for on_value, app in apps:
            try:
                app, ppkwargs = app  # user can optionally pass doubles
            except TypeError:
                ppkwargs = {}
            # doesn't currently load "composed" apps
            client.load_app(
                app,
                on_value=on_value,
                **ppkwargs
            )
    # client setup/teardown
    client.listener.start()
    yield client

    # unload app set
    if apps:
        for value, app in apps:
            client.unload_app(value)

    client.listener.disconnect()
    client.disconnect()


def get_pool(contacts, **kwargs):
    """Construct and return a slave pool from a sequence of
    contact information.
    """
    assert not isinstance(contacts, str)
    from .distribute import SlavePool
    SlavePair = namedtuple("SlavePair", "client listener")
    pairs = deque()

    # instantiate all pairs
    for contact in contacts:
        if isinstance(contact, str):
            contact = (contact,)
        # create pairs
        listener = EventListener(*contact, **kwargs)
        client = Client(
            *contact,
            listener=listener,
            call_tracking_header=kwargs.get('call_tracking_header')
        )
        pairs.append(SlavePair(client, listener))

    return SlavePool(pairs)
