# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Rudimentary system stats collection using ``psutil``.
"""
import time
from switchy import event_callback, utils


def sys_stats(df):
    """Reindex on the call index to allign with call metrics data
    and interpolate.
    """
    df.index = df.call_index
    ci = df.pop('call_index')
    # iterpolate all system stats since the arrays will be sparse
    # compared to the associated call metrics data.
    return df.reindex(range(int(ci.iloc[-1]) + 1)).interpolate()


class SysStats(object):
    """A switchy app for capturing system performance stats during load test
    using the `psutil`_ module.

    An instance of this app should be loaded if rate limited data gathering is
    to be shared across multiple slaves (threads).

    .. _psutil:
        https://pythonhosted.org/psutil/
    """
    operators = {
        'sys_stats': sys_stats,
    }

    def __init__(self, psutil, rpyc=None):
        self._psutil = psutil
        self.rpyc = rpyc
        self._conn = None
        self.log = utils.get_logger(__name__)
        # required to define the columns for the data frame storer
        self.fields = [
            'call_index',
            'total_cpu_percent',
            'percent_cpu_sys',
            'percent_cpu_usr',
            'percent_cpu_idle',
            'percent_cpu_iow',
            'phymem_percent_usage',
            'load_avg',
        ]
        # this call should ensure we have the correct type
        self._times_tup_type = psutil.cpu_times().__class__
        self.log = utils.get_logger(type(self).__name__)

        # initial cpu usage
        self._last_cpu_times = self.psutil.cpu_times()

    @property
    def psutil(self):
        try:
            return self._psutil
        except ReferenceError, EOFError:  # rpyc and its weakrefs being flaky
        # except Exception:
            if self.rpyc:
                self.log.warn("resetting rypc connection...")
                self._conn = conn = self.rpyc.classic_connect()
                self._psutil = conn.modules.psutil
                return self._psutil
            raise

    def prepost(self, collect_rate=2, storer=None):
        self.storer = storer
        self.count = 0
        self._collect_period = 1. / collect_rate
        self._last_collect_time = 0

    @property
    def collect_rate(self):
        return 1. / self._collect_period

    @collect_rate.setter
    def collect_rate(self, rate):
        self._collect_period = 1. / rate

    @event_callback("CHANNEL_CREATE")
    def on_create(self, sess):
        now = time.time()
        if sess.is_outbound():
            # rate limiting
            if (now - self._last_collect_time) >= self._collect_period:
                # XXX important to keep this here for performance and
                # avoiding thread racing
                self._last_collect_time = now

                psutil = self.psutil
                self.log.debug("writing psutil row at time '{}'".format(now))

                curr_times = self.psutil.cpu_times()

                delta = self._times_tup_type(*tuple(
                        now - last for now, last in
                        zip(curr_times, self._last_cpu_times)
                ))
                self._last_cpu_times = curr_times
                tottime = sum(delta)

                self.storer.append_row((
                    sess.call.vars['call_index'],
                    psutil.cpu_percent(interval=None),
                    delta.system / tottime * 100.,
                    delta.user / tottime * 100.,
                    delta.idle / tottime * 100.,
                    delta.iowait / tottime * 100.,
                    psutil.phymem_usage().percent,
                    psutil.os.getloadavg()[0],
                ))
