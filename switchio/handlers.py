# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
High level event processing machinery.

Includes handlers for tracking FreeSWITCH minion state through event
processing and session modelling.
Default event handlers for session, call and background job management
are defined here.
"""
import operator
import time
import multiprocessing as mp
from collections import deque, OrderedDict, Counter
from .marks import handler, get_callbacks
from .connection import ConnectionError
from .async import get_event_loop
from . import utils
from .models import Job, Call


if utils.py35:
    from .py3_models import Session
else:
    from .models import Session


class EventListener(object):
    """``Session``, ``Call`` and ``Job`` tracking through a default set of
    event handlers.

    Tracks various session entities by wrapping received event data in local
    ``models`` APIs and/or data structures. Serves as a higher level API on
    top of the underlying event loop.
    """
    def __init__(
        self,
        event_loop,
        call_tracking_header='variable_call_uuid',
        autorecon=30,
        max_limit=float('inf'),
    ):
        """
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
        """
        self.event_loop = event_loop
        if getattr(event_loop, '_run_loop', None):
            self._tx_con = self.event_loop._rx_con
        else:  # SWIG requires 2 due to lack of thread safety
            self._tx_con = self.event_loop._rx_con.new_connection()
        self.sessions = OrderedDict()
        self.log = utils.get_logger(utils.pstr(self))
        # store last 1k of each type of failed session
        self.failed_sessions = OrderedDict()
        self.bg_jobs = OrderedDict()
        self.calls = OrderedDict()  # maps aleg uuids to Sessions instances
        self.hangup_causes = Counter()  # record of causes by category
        self.sessions_per_app = Counter()
        self.max_limit = max_limit
        self.call_tracking_header = call_tracking_header
        self.autorecon = autorecon
        # job synchronization
        self._lookup_blocker = mp.Event()  # used block event loop temporarily
        self._lookup_blocker.set()
        # state reset
        self.reset()

        # add default handlers
        for evname, cbtype, cb in get_callbacks(self, only='handler'):
            self.event_loop.add_handler(evname, cb)

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

    def count_jobs(self):
        return len(self.bg_jobs)

    def count_sessions(self):
        return len(self.sessions)

    def count_calls(self):
        '''Count the number of active calls hosted by the slave process
        '''
        return len(self.calls)

    def count_failed(self):
        '''Return the failed session count
        '''
        return sum(
            self.hangup_causes.values()
        ) - self.hangup_causes['NORMAL_CLEARING']

    def reset(self):
        '''Clear all internal stats and counters
        '''
        self.log.debug('resetting all stats...')
        self.hangup_causes.clear()
        self.failed_jobs = Counter()
        self.total_answered_sessions = 0

    def get_body(self, event):
        if getattr(event, 'getBody', None):
            return event.getBody()
        else:
            return operator.itemgetter('Body')(event)

    @handler('CHANNEL_PARK')
    @handler('CALL_UPDATE')
    def lookup_sess(self, e):
        """The most basic handler template which looks up the locally tracked
        session corresponding to event `e` and updates it with event data
        """
        uuid = e.get('Unique-ID')
        sess = self.sessions.get(uuid, False)
        if sess:
            sess.update(e)
            return True, sess
        return False, None

    @handler('LOG')
    def _handle_log(self, e):
        self.log.info(self.get_body(e))
        return True, None

    @handler('SERVER_DISCONNECTED')
    def _handle_disconnect(self, e):
        """optionally poll waiting for connection to resume until timeout
        or shutdown
        """
        self.log.warning("handling DISCONNECT from server '{}'"
                         .format(self.host))
        if getattr(self.event_loop, '_run_loop', None):
            self.log.warning("No auto-reconnect support yet on py35+")
            return True, None

        self.disconnect()
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
                    assert self.event_loop.connected()
                    assert self.is_alive()
                    return True, None
                    # if we couldn't reconnect then have this thread exit
                    self._exit.set()
                    self.log.warning(
                        "Reconnection attempts to '{}' failed. Please call"
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
        job_uuid = e.get('Job-UUID')
        body = self.get_body(e)
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

    @handler('CHANNEL_CREATE')
    @handler('CHANNEL_ORIGINATE')
    def _handle_initial_event(self, e):
        '''Handle channel create events by building local
        `Session` and `Call` objects for state tracking.
        '''
        uuid = e.get('Unique-ID')
        # Record the newly activated session
        # TODO: pass con as weakref?
        con = self._tx_con

        # short circuit if we have already allocated a session since FS is
        # indeterminate about which event create|originate will arrive first
        sess = self.sessions.get(uuid)
        if sess:
            return True, sess

        # allocate a session model
        sess = Session(e, event_loop=self.event_loop, uuid=uuid, con=con)
        direction = sess['Call-Direction']
        self.log.debug("{} session created with uuid '{}'".format(
                       direction, uuid))
        sess.cid = self.event_loop.get_id(e, 'default')

        # Use our specified "call identification variable" to try and associate
        # sessions into calls. By default the 'variable_call_uuid' channel
        # variable is used for tracking locally bridged calls
        call_uuid = e.get(self.call_tracking_header)  # could be 'None'
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

    @handler('CHANNEL_ANSWER')
    def _handle_answer(self, e):
        '''Handle answer events

        Returns
        -------
        sess : session instance corresponding to uuid
        '''
        uuid = e.get('Unique-ID')
        sess = self.sessions.get(uuid, None)
        if sess:
            self.log.debug('answered session {} with call direction {}'
                           .format(uuid,  e.get('Call-Direction')))
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
        uuid = e.get('Unique-ID')
        sess = self.sessions.pop(uuid, None)
        direction = sess['Call-Direction'] if sess else 'unknown'
        if not sess:
            return False, None
        sess.update(e)
        sess.hungup = True
        cause = e.get('Hangup-Cause')
        self.hangup_causes[cause] += 1  # count session causes
        self.sessions_per_app[sess.cid] -= 1

        # if possible lookup the relevant call
        call_uuid = e.get(self.call_tracking_header)
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

    @property
    def host(self):
        return self.event_loop.host

    def is_alive(self):
        return self.event_loop.is_alive()

    def is_running(self):
        return self.event_loop.is_running()

    def connect(self):
        self.event_loop.connect()
        self._tx_con.connect()

    def connected(self):
        return self.event_loop.connected()

    def start(self):
        return self.event_loop.start()

    def disconnect(self):
        self.event_loop.disconnect()
        self._tx_con.disconnect()

    def unsubscribe(self, evname):
        return self.event_loop.unsubscribe(evname)


def get_listener(host, port=8021, password='ClueCon', **kwargs):
    id_headers = kwargs.pop('app_id_headers', {})
    el = get_event_loop(host, port, password, app_id_headers=id_headers)
    return EventListener(el, **kwargs)
