# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Call generator app for load testing
"""
from __future__ import division
import time
import sched
import traceback
import inspect
from itertools import cycle
from collections import Counter
from threading import Thread
import multiprocessing as mp
from .. import utils
from .. import marks
from .. import api
from .. import handlers
from . import AppManager
from .measure import CDR


def get_originator(contacts, *args, **kwargs):
    """Originator factory
    """
    try:
        if isinstance(contacts, basestring):
            contacts = (contacts,)
    except NameError:  # py3 compat
        if isinstance(contacts, str):
            contacts = (contacts,)

    # pop kwargs destined for the listener
    _, kwargnames = utils.get_args(handlers.get_listener)
    lkwargs = {name: kwargs.pop(name) for name in kwargnames if name in kwargs}

    slavepool = api.get_pool(contacts, **lkwargs)
    return Originator(slavepool, *args, **kwargs)


def limiter(pairs):
    """Yield slave pairs up until a slave has reached a number of calls
    less then or equal to it's predefined capacity limit
    """
    for pair in cycle(pairs):
        el = pair.listener
        if el.count_calls() > el.max_limit:
            continue
        yield pair


class WeightedIterator(object):
    """Pseudo weighted round robin iterator. Delivers items interleaved
    in weighted order.
    """
    def __init__(self, counter=None):
        self.weights = counter or Counter()
        self.counts = self.weights.copy()
        attr = '__getitem__'
        setattr(self.__class__, attr, getattr(self.weights, attr))

    def __repr__(self):
        return '{}({})'.format(type(self).__name__, repr(self.weights))

    def __setitem__(self, key, value):
        self.weights[key] = value
        self.counts = self.weights.copy()

    def cycle(self):
        """Endlessly iterates the most up to date keys in `counts`.
        Allows for real-time weight updating from another thread.
        """
        while True:
            if not self.weights:
                raise StopIteration("no items in multiset")
            for item in self.counts:
                yield item

    def __iter__(self):
        """Iterate items in interleaved order until a particular item's weight
        has been exhausted
        """
        for item in self.cycle():
            if self.counts[item] > 0:
                yield item
                self.counts[item] -= 1

            # all counts have expired so reset
            if not any(self.counts.values()):
                self.counts = self.weights.copy()


class State(object):
    """Enumeration to represent the originator state machine
    """
    __slots__ = ['value']

    INITIAL = 0  # Originator is initialized and is awaiting start command
    ORIGINATING = 1  # Calls are currently being originated
    STOPPED = 2  # There are no more active calls/sessions and bgjobs

    def __init__(self, state=INITIAL):
        self.value = state

    def __str__(self):
        names, vals = zip(*self.__class__.__dict__.items())
        index = vals.index(self.value)
        return names[index]
        return names[vals.index(self.value)]


class Originator(object):
    """An auto-dialer built for stress testing.
    """
    default_settings = [
        ('rate', 30),  # call offer rate in cps
        ('limit', 1),  # concurrent calls limit (i.e. erlangs)
        ('max_offered', float('inf')),  # max offered calls
        ('duration', 0),
        ('period', 1),
        ('uuid_gen', utils.uuid),
        ('rep_fields_func', lambda: {}),
        ('autohangup', True),
    ]

    def __init__(self, slavepool, debug=False, auto_duration=True,
                 app_id=None, **kwargs):
        '''
        Parameters
        ----------
        slavepool : SlavePool instance
            slave pool of (Client, EventListener) pairs to use for call
            generation
        debug : bool
            toggle debug logging on the slave servers
        auto_duration : bool
            determines whether to recalculate call hold times when adjusting
            rate or limit setting
        app_id : str
            id to use
        '''
        self.pool = slavepool
        self.iternodes = limiter(slavepool.nodes)
        self.count_calls = self.pool.fast_count
        self.debug = debug
        self.auto_duration = auto_duration
        self.host = self.pool.evals('client.host')
        self.log = utils.get_logger(utils.pstr(self))
        self._thread = None
        self._start = mp.Event()
        self._exit = mp.Event()
        self._burst = mp.Event()
        self._state = State()
        # load settings
        self._rate = None
        self._limit = None
        self._duration = None
        self._max_rate = 250  # a realistic hard cps limit
        self.duration_offset = 5  # calls must be at least 5 secs

        self.app_manager = AppManager(self.pool)
        self.measurers = self.app_manager.measurers
        self.measurers.add(CDR(), pool=self.pool)

        # don't worry so much about call state for load testing
        self.pool.evals('listener.unsubscribe("CALL_UPDATE")')
        self.pool.evals('listener.connect()')
        self.pool.evals('client.connect()')

        self.app_weights = WeightedIterator()
        self.iterappids = iter(self.app_weights)

        # apply default load settings
        if len(kwargs):
            self.log.debug("kwargs contents : {}".format(kwargs))

        # assign defaults
        for name, val in type(self).default_settings:
            setattr(self, name, kwargs.pop(name, None) or val)

        if len(kwargs):
            raise TypeError("Unsupported kwargs: {}".format(kwargs))

        # burst loop scheduler
        self.sched = sched.scheduler(time.time, time.sleep)
        self.setup()
        # counters
        self._total_originated_sessions = 0

    # XXX: instead make this a `prepost` hook?
    def setup(self):
        """Apply load test settings on the slave server
        """
        # Raise the sps and max_sessions limit so they do not obstruct our
        # load settings
        self.pool.evals('client.api("fsctl sps {}")'.format(10000))
        self.pool.evals('client.api("fsctl max_sessions {}")'.format(10000))
        self.pool.evals('client.api("fsctl verbose_events true")')

        # Reduce logging level to avoid too much output in console/logfile
        if self.debug is True:
            self.log.info("setting debug logging on slaves!")
            self.pool.evals('client.api("fsctl loglevel debug")')
            self.pool.evals('client.api("console loglevel debug")')
        else:
            self.pool.evals('client.api("fsctl loglevel warning")')
            self.pool.evals('client.api("console loglevel warning")')

    def load_app(self, app, app_id=None, ppkwargs={}, weight=1,
                 with_metrics=True):
        """Load a call control app for use across the entire slave cluster.

        If `app` is an instance then it's state will be shared by all slaves.
        If it is a class then new instances will be instantiated for each
        `Client`-`Observer` pair and thus state will have per slave scope.
        """
        appid = self.app_manager.load_multi_app(
            # always register our local callbacks for all apps/slaves
            [(app, ppkwargs), self],
            app_id=app_id,
            with_measurers=with_metrics
        )
        self.app_weights[appid] = weight
        # refresh load settings
        for attr in 'duration rate limit'.split():
            setattr(self, attr, getattr(self, attr))
        return app_id

    @property
    def max_rate(self):
        """The maximum `rate` value which can be set.
        Setting `rate` any higher will simply clip to this value.
        """
        return self._max_rate

    def _get_rate(self):
        return self._rate

    def _set_rate(self, value):
        burst_rate = float(min(self.max_rate, value))
        # set the 'inter-burst-period' accounting for surrounding processing
        # latencies by a small %
        self.ibp = 1 / burst_rate * 0.90
        self._rate = value

        # update any sub-apps
        for app in self.app_manager.iterapps():
            callback = getattr(app, '__setrate__', None)
            if callback:
                # XXX assumes equal delegation to all slaves
                callback(value / float(len(self.pool)))

        if self.auto_duration and self.limit:
            self.duration = self.limit / value + self.duration_offset

    rate = property(_get_rate, _set_rate, "Call rate (cps)")

    def _get_limit(self):
        return self._limit

    # TODO: auto_duration should be applied via decorator?
    def _set_limit(self, value):
        # update any sub-apps
        for app in self.app_manager.iterapps():
            callback = getattr(app, '__setlimit__', None)
            if callback:
                callback(value)

        self._limit = value
        if self.auto_duration:
            self.duration = value / self.rate + self.duration_offset

    limit = property(_get_limit, _set_limit,
                     "Number of simultaneous calls allowed  (i.e. erlangs)")

    def _get_duration(self):
        return self._duration

    def _set_duration(self, value):
        # update any sub-apps
        for app in self.app_manager.iterapps():
            callback = getattr(app, '__setduration__', None)
            if callback:
                callback(value)
        # apply the new duration
        self._duration = value

    duration = property(_get_duration, _set_duration, "Call duration (secs)")

    def __dir__(self):
        return utils.dirinfo(self)

    def __repr__(self):
        """Repr with [<state>] <load_settings> slapped in
        """
        props = "state total_originated_sessions rate limit max_offered "\
                "duration".split()
        rep = type(self).__name__
        return "<{}: active-calls={} {}>".format(
            rep, self.pool.fast_count(),
            " ".join("{}={}".format(
                attr.replace('_', '-'), getattr(self, attr)) for attr in props)
        )

    def _report_on_none(self):
        if self.pool.count_jobs() == 0 and self.pool.count_sessions() == 0:
            self.log.info('all sessions have ended...')

    @marks.event_callback("BACKGROUND_JOB")
    def _handle_bj(self, sess, job):
        '''Check for all jobs complete
        '''
        # if duration == 0 then never schedule hangup events
        if sess and not sess.call.vars.get('noautohangup') and self.duration:
            self.log.debug("scheduling auto hangup for '{}'"
                           .format(sess.uuid))
            # schedule hangup
            if self.autohangup:
                remaining = self.duration - sess.uptime
                if remaining > 0:
                    sess.sched_hangup(remaining)
                else:
                    sess.hangup()
            else:
                # call duration should always be started after the connect
                sess.sched_hangup(remaining)

        # failed jobs and sessions should be popped in the listener's
        # default bg job handler
        self._report_on_none()

    @marks.event_callback("CHANNEL_HANGUP")
    def _handle_hangup(self, sess):
        self._report_on_none()
        # if sess.call.sessions and sess.is_outbound():
        #     # we normally expect that the caller hangs up
        #     self.log.warn(
        #         'received hangup for inbound session {}'
        #         .format(sess.uuid)
        #     )

    @marks.event_callback("CHANNEL_ORIGINATE")
    def _handle_originate(self, sess):
        '''Set the call duration
        '''
        # use our tx for session commands
        # with sess(self.ctl._con):
        # sess.con = self.ctl._con

        # if max sessions are already up, stop
        self._total_originated_sessions += 1
        self._check_max()
        # remove our con from the session
        # sess.con = None

    def _check_max(self):
        if self._total_originated_sessions >= self.max_offered:
            self._burst.clear()  # signal to stop the burst loop
            self.log.info("'{}' sessions have been originated but"
                          " max allowed is '{}', exiting run loop..."
                          .format(self._total_originated_sessions,
                                  self.max_offered))

    @property
    def total_originated_sessions(self):
        return self._total_originated_sessions

    def _burst_loop(self):
        '''Originate calls via a bgapi/originate call in a loop
        '''
        originated = 0
        count_calls = self.count_calls
        iterappids = self.iterappids
        num = min((self.limit - count_calls(), self.rate))
        self.log.debug("bursting num originates = {}".format(num))
        if num <= 0:
            self.log.debug(
                "maximum simultaneous sessions limit '{}' reached..."
                .format(self.limit))

        # TODO: need a proper traffic scheduling algo here!
        # try to launch 'rate' calls in a loop
        for _, node in zip(range(num), self.iternodes):
            if not self.check_state("ORIGINATING"):
                break
            if count_calls() >= self.limit:
                break
            self.log.debug("count calls = {}".format(count_calls()))
            # originate a call
            node.client.originate(
                app_id=next(iterappids),
                uuid_func=self.uuid_gen,
                rep_fields=self.rep_fields_func()
            )
            originated += 1
            # limit the max transmission rate
            time.sleep(self.ibp)

        if originated > 0:
            self.log.debug('Requested {} new sessions'
                           .format(originated))

    def _serve_forever(self):
        """Call burst loop entry point.
        This method blocks until all calls have finished.
        A background thread waits in initial state until started.
        """
        try:
            while not self._exit.is_set():
                # block until start cmd recieved
                self._start.wait()
                # check again for exit event just after start trigger
                if self._exit.is_set():
                    continue
                if not self.originate_cmd[0]:
                    raise utils.ConfigurationError(
                        "you must first set an originate command")
                # if no pending tasks, insert a burst loop
                if self.sched.empty():
                    self.sched.enter(0, 1, self._burst_loop, [])

                # task loop
                self._change_state("ORIGINATING")
                try:
                    while self._burst.is_set():
                        prerun = time.time()
                        # NOTE: if we ever want to schedule other types
                        # of tasks we will need to move the enterabs below
                        # into _burst as it was previously.
                        # block until there are available tasks
                        self.sched.run()
                        # schedule the next re-entry
                        if self.check_state("ORIGINATING"):
                            self.log.debug('next burst loop re-entry is in {} '
                                           'seconds'.format(self.period))
                            self.sched.enterabs(prerun + self.period, 1,
                                                self._burst_loop, ())
                except Exception:
                    self.log.error("exiting burst loop due to exception:\n{}"
                                   .format(traceback.format_exc()))

                self.log.info("stopping burst loop...")
                self._change_state("STOPPED")

            # exit gracefully
            self.log.info("terminating originate thread...")
            self._change_state("STOPPED")
        except Exception:
            self.log.exception(
                "'{}' failed with:".format(mp.current_process().name)
            )

    @property
    def state(self):
        """The current operating state as a string
        """
        return str(self._state)

    def _change_state(self, ident):
        init_state = self.state
        if not self.check_state(ident):
            self._state.value = getattr(State, ident)
            self.log.info("State Change: '{}' -> '{}'".format(
                          init_state, self.state))

    def check_state(self, ident):
        '''Compare current state to ident
        '''
        return self._state.value == getattr(State, ident)

    def stopped(self):
        '''Return bool indicating if in the stopped state.
        '''
        return self._state.value == State.STOPPED

    def start(self):
        """Start the originate burst loop by starting and/or notifying a worker
        thread to begin. Changes state INITIAL | STOPPED -> ORIGINATING.
        """
        if not self.app_weights.weights:
            raise utils.ConfigurationError("No apps have been loaded")

        if not any(self.pool.evals('listener.is_running()')):
            # Do listener(s) startup here so that additional apps
            # can be loaded just prior. Currently there is a restriction
            # since new event subscriptions (as required by most apps)
            # must be issued *before* starting the listener event loop
            # since the underlying connection is mutexed.
            self.pool.evals('listener.start()')

        if self._thread is None or not self._thread.is_alive():
            self.log.debug("starting burst loop thread")
            self._thread = Thread(target=self._serve_forever,
                                  name='switchio_burst_loop')
            self._thread.daemon = True  # die with parent
            self._thread.start()
            time.sleep(0.1)
        # trigger burst loop entry
        self._start.set()
        self._burst.set()
        self._start.clear()

    def is_alive(self):
        """Indicate whether the call burst thread is up
        """
        return self._thread.is_alive() if self._thread else False

    def stop(self):
        '''
        Stop originate loop if currently originating sessions.
        Change state ORIGINATING -> STOPPED
        '''
        if not self.check_state("STOPPED"):
            self.log.info("Stopping sessions origination loop...")
        else:
            self.log.info("Originator in '{}'' state, nothing to stop..."
                          .format(self._state))
        self._burst.clear()  # signal to stop the burst loop

    def hupall(self):
        '''Send the 'hupall' command to hangup all active calls.
        '''
        self.log.warn("Stopping all calls with hupall!")
        # set stopped state - no further bursts will be scheduled
        self.stop()
        return self.pool.evals('client.hupall()')

    def hard_hupall(self):
        """Hangup all calls for all slaves, period, even if they weren't originated by
        this instance and stop the burst loop.
        """
        self.stop()
        return self.pool.evals("client.cmd('hupall')")

    def shutdown(self):
        '''Shutdown this originator instance and hanging up all
        active calls and triggering the burst loop to exit.
        '''
        if self.pool.count_sessions():
            self.hupall()
        else:
            self.stop()
        self._exit.set()  # trigger burst thread exit

    @property
    def originate_cmd(self):
        """Originate str used for making calls
        """
        return self.pool.evals('client.originate_cmd')

    def _clearall(self):
        """Clear all listener model collections.
        (Handy if a bunch of stale calls are present)
        """
        self.pool.evals('listener.sessions.clear()')
        self.pool.evals('listener.calls.clear()')
        self.pool.evals('listener.bg_jobs.clear()')

    def _reset_connections(self):
        self.pool.evals('listener.disconnect()')
        self.pool.evals('listener.connect()')

    def waitforstate(self, state, **kwargs):
        """Block until the internal state matches ``state``.
        """
        return self.waitwhile(lambda: not self.check_state(state))

    def waitwhile(self, predicate=None, **kwargs):
        """Block until ``predicate`` evaluates to ``False``.

        The default predicate waits for all calls to end and for activation of
        the "STOPPED" state.

        See `switchio.utils.waitwhile` for more details on predicate usage.
        """
        def calls_active():
            return self.count_calls() or not self.stopped()

        predicate = predicate or calls_active
        assert inspect.isfunction(predicate), "{} must be a function".format(
            predicate)

        # poll for predicate to eval False
        return utils.waitwhile(predicate=predicate, **kwargs)
