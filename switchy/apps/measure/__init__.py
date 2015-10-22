# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Measurements app for collecting call latency and performance stats.
"""
import weakref
import time
from switchy.marks import event_callback
from switchy import utils
from .metrics import pd, DataStorer


def call_metrics(df):
    """Default call measurements computed from data retrieved by
    the `SessionTimes` app.
    """
    # sort by create time
    df = df.sort(columns=['caller_create'])
    cr = 1 / df['caller_create'].diff()  # compute instantaneous call rates
    clippedcr = cr.clip(upper=1000)

    mdf = pd.DataFrame(
        data={
            'switchy_app': df['switchy_app'],
            'hangup_index': df.index,
            'invite_latency': df['callee_create'] - df['caller_create'],
            'answer_latency': df['caller_answer'] - df['callee_answer'],
            'call_setup_latency': df['caller_answer'] - df['caller_create'],
            'originate_latency': df['caller_req_originate'] - df['job_launch'],
            'call_duration': df['caller_hangup'] - df['caller_create'],
            'failed_calls': df['failed_calls'],
            'active_sessions': df['active_sessions'],
            'call_rate': clippedcr,
            'avg_call_rate': pd.rolling_mean(clippedcr, 100),
            'seizure_fail_rate': df['failed_calls'] / df.index.max(),
        },
        # data will be sorted by 'caller_create` but re-indexed
        index=range(len(df)),
    ).assign(answer_seizure_ratio=lambda df: 1 - df['seizure_fail_rate'])

    return mdf


def call_types(df, figspec=None):
    """Hangup-cause and app plotting annotations
    """
    # sort by create time
    df = df.sort(columns=['caller_create'])
    ctdf = pd.DataFrame(
        data={
            'hangup_cause': df['hangup_cause'],
        },
        # data will be sorted by 'caller_create` but re-indexed
        index=range(len(df)),
    )

    # create step funcs for each hangup cause
    for cause in ctdf.hangup_cause.value_counts().keys():
        ctdf[cause.lower()] = (ctdf.hangup_cause == cause).astype(pd.np.float)

    return ctdf


call_metrics.figspec = {
    (1, 1): [
        'call_setup_latency',
        'answer_latency',
        'invite_latency',
        'originate_latency',
    ],
    (2, 1): [
        'active_sessions',
        'failed_calls',
    ],
    (3, 1): [
        'call_rate',
        'avg_call_rate',  # why so many NaN?
    ],
}


class CallTimes(object):
    """Collect call oriented event time stamps and load data which can be used
    for per call metrics computations.
    """
    fields = [
        'switchy_app',
        'hangup_cause',
        'caller_create',
        'caller_answer',
        'caller_req_originate',
        'caller_originate',
        'caller_hangup',
        'job_launch',
        'callee_create',
        'callee_answer',
        'callee_hangup',
        'failed_calls',
        'active_sessions',
    ]

    operators = {
        'call_metrics': call_metrics,
        'call_types': call_types,
    }

    def __init__(self):
        self.log = utils.get_logger(__name__)

    def new_storer(self):
        return DataStorer(columns=self.fields)

    def prepost(self, listener, storer=None, pool=None, orig=None):
        self.listener = listener
        self.orig = orig
        # create our own storer if we're not loaded as a `Measurer`
        self._ds = storer if storer else self.new_storer()
        self.pool = weakref.proxy(pool) if pool else self.listener

    @property
    def storer(self):
        return self._ds

    @event_callback('CHANNEL_CREATE')
    def on_create(self, sess):
        """Store total (cluster) session count at channel create time
        """
        # capture the current erlangs / call count
        sess.call.vars['session_count'] = self.pool.count_sessions()

    @event_callback('CHANNEL_ORIGINATE')
    def on_originate(self, sess):
        # store local time stamp for originate
        sess.times['originate'] = sess.time
        sess.times['req_originate'] = time.time()

    @event_callback('CHANNEL_ANSWER')
    def on_answer(self, sess):
        sess.times['answer'] = sess.time

    @event_callback('CHANNEL_HANGUP')
    def log_stats(self, sess, job):
        """Append measurement data only once per call
        """
        sess.times['hangup'] = sess.time
        call = sess.call

        if call.sessions:  # still session(s) remaining to be hungup
            call.caller = call.first
            call.callee = call.last
            if job:
                call.job = job
            return

        # all other sessions have been hungup so store all measurements
        caller = getattr(call, 'caller', None)
        if not caller:
            # most likely only one leg was established and the call failed
            # (i.e. call.caller was never assigned above)
            if not sess.is_outbound():
                self.log.warn(
                    'received hangup for inbound session {}'
                    .format(sess.uuid)
                )
            caller = sess
        callertimes = caller.times
        callee = getattr(call, 'callee', None)
        calleetimes = callee.times if callee else None

        pool = self.pool
        job = getattr(call, 'job', None)
        rollover = self._ds.append_row((
            caller.appname,
            caller['Hangup-Cause'],
            callertimes['create'],  # invite time index
            callertimes['answer'],
            callertimes['req_originate'],  # local time stamp
            callertimes['originate'],
            callertimes['hangup'],
            # 2nd leg may not be successfully established
            job.launch_time if job else None,
            calleetimes['create'] if callee else None,
            calleetimes['answer'] if callee else None,
            calleetimes['hangup'] if callee else None,
            pool.count_failed(),
            call.vars['session_count'],
        ))
        if rollover:
            self.log.debug('wrote data to disk')
