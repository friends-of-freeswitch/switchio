# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Server components for building clustered call processing systems.
"""
from . import utils
from .apps import AppManager
from .observe import get_pool


class Service(object):
    """Serve centralized, long running, call processing apps on top of a
    FreeSWITCH cluster.
    """
    def __init__(self, contacts, **kwargs):
        kwargs.setdefault('call_tracking_header', 'variable_call_uuid')
        self.pool = get_pool(contacts, **kwargs)
        self.apps = AppManager(self.pool)
        self.host = self.pool.evals('listener.host')
        self.log = utils.get_logger(utils.pstr(self))
        # initialize all reactor event loops
        self.pool.evals('listener.connect()')
        self.pool.evals('client.connect()')

    def run(self, block=True):
        """Run service optionally blocking until stopped.
        """
        self.pool.evals('listener.start()')
        assert all(self.pool.evals('listener.is_alive()'))
        if block:
            try:
                self.pool.evals('listener.wait()')
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()

    def is_alive(self):
        """Return bool indicating if a least one event loop is alive.
        """
        return any(self.pool.evals('listener.is_alive()'))

    def stop(self):
        """Stop service and disconnect.
        """
        self.pool.evals('listener.disconnect()')
        self.pool.evals('listener.wait(1)')
