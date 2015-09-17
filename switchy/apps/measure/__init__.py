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
            'call_rate': cr.clip(upper=1000),
            'avg_call_rate': pd.rolling_mean(cr, 30),
            'seizure_fail_rate': df['failed_calls'] / df.index.max()
        },
        # data will be sorted by 'caller_create` but re-indexed
        index=range(len(df)),
    ).assign(answer_seizure_ratio=lambda df: 1 - df['seizure_fail_rate'])

    return mdf


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
    ]
}


class CallTimes(object):
    """Collect call oriented event time stamps and load data which can be used
    for per call metrics computations.
    """
    fields = [
        'switchy_app',
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

    operators = {'call_metrics': call_metrics}

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
        sess.call.vars['session_count'] = self.pool.count_sessions()

    @event_callback('CHANNEL_ORIGINATE')
    def on_originate(self, sess):
        # store local time stamp for originate
        sess.times['originate'] = sess.time
        sess.times['req_originate'] = time.time()

    @event_callback('CHANNEL_HANGUP')
    def log_stats(self, sess, job):
        """Append measurement data only once per call
        """
        # TODO: eventually we should use a data type which allows the
        # separation of metrics between those that require two vs. one
        # leg to calculate?
        call = sess.call
        if call.sessions:  # still session(s) remaining to be hungup
            call.caller = call.first
            call.callee = call.last
            if job:
                call.job = job
            return

        # all other sessions have been hungup so store all measurements
        pool = self.pool
        caller, callee = call.caller.times, call.callee.times
        job = getattr(call, 'job', None)
        rollover = self._ds.append_row((
            call.caller.appname,
            caller['create'],  # invite time index
            caller['answer'],
            caller['req_originate'],  # local time stamp
            caller['originate'],
            caller['hangup'],
            job.launch_time if job else None,
            callee['create'],
            callee['answer'],
            callee['hangup'],
            pool.count_failed(),
            sess.call.vars['session_count'],
        ))
        if rollover:
            self.log.debug('wrote data to disk')
