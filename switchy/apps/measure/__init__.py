# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Measurements app for collecting call latency and performance stats.
"""
import weakref
from switchy.marks import event_callback
from switchy import utils
from metrics import new_array


class Metrics(object):
    """Collect call oriented measurements

    Only an instance of this class can be loaded as switchy app
    """
    def __init__(self, listener=None, array=None, pool=None):
        self.listener = weakref.proxy(listener) if listener else None
        self._array = array if array else new_array()  # np default buffer
        self.log = utils.get_logger(__name__)
        self.pool = pool if pool else self.listener

    def prepost(self, listener, array=None, pool=None):
        if array is not None:  # array can be overriden at app load time
            self._array = array
        if not self.listener:
            self.listener = listener
        self.pool = pool if pool else self.listener
        yield
        self.listener = None
        self.slaves = None

    @property
    def array(self):
        return self._array

    @event_callback('CHANNEL_HANGUP')
    def log_stats(self, sess, job):
        """Append measurement data inserting only once per call
        """
        # TODO: eventually we should use a data type which allows the
        # separation of metrics between those that require two vs. one
        # leg to calculate?
        l = self.listener
        pool = self.pool
        if sess.call.sessions:
            # the `callee` UA is who's time measures we want
            partner_sess = sess.call.sessions[-1]
            if l.sessions.get(partner_sess.uuid, False):
                rollover = self._array.insert((
                    sess.create_time,  # invite time index
                    abs(sess.create_time - partner_sess.create_time),
                    abs(sess.answer_time - partner_sess.answer_time),
                    abs(sess.answer_time - sess.create_time),
                    sess.originate_time - job.launch_time if job else 0,
                    pool.count_failed() if pool else 0,
                    pool.count_sessions(),
                ))
                if rollover:
                    self.log.warn('resetting metric buffer index!')
