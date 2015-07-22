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
    def __init__(self):
        self.log = utils.get_logger(__name__)

    def prepost(self, listener, array=None, pool=None):
        self.listener = listener
        # array can be overriden at app load time
        self._array = array if array else new_array()  # np default buffer
        self.pool = weakref.proxy(pool) if pool else self.listener

    @property
    def array(self):
        return self._array

    @event_callback('CHANNEL_HANGUP')
    def log_stats(self, sess, job):
        """Append measurement data inserting only once per call
        """
        call = sess.call
        # ensure this is NOT the last active session in the call
        if not call.sessions:
            # all other sessions in call have been hungup and this is
            # the last so all measurements should already have been collected
            return

        # TODO: eventually we should use a data type which allows the
        # separation of metrics between those that require two vs. one
        # leg to calculate?
        l = self.listener
        pool = self.pool

        peer = sess.call.get_peer(sess)
        if peer and l.sessions.get(peer.uuid, False):
            first = call.first
            last = call.last
            rollover = self._array.insert((
                first.create_time,  # invite time index
                last.create_time - first.create_time,
                last.answer_time - first.answer_time,
                first.answer_time - first.create_time,
                first.originate_time - job.launch_time if job else 0,
                first.originate_event_time - first.create_time if job else 0,
                pool.count_failed() if pool else 0,
                pool.count_sessions(),
            ))
            if rollover:
                self.log.warn('resetting metric buffer index!')
