# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Routing apps
"""
from collections import Counter
from ..marks import event_callback
from ..apps import app
from ..utils import get_logger

@app
class Bridger(object):
    '''Bridge sessions within a call an arbitrary number of times.
    '''
    def prepost(self):
        self.log = get_logger(self.__class__.__name__)
        self.call2entries = Counter()
        self.count2bridgeargs = {  # leg count to codec spec
            1: 'proxy'  # default is to proxy the call using the request uri
        }

    @event_callback("CHANNEL_PARK")
    def on_park(self, sess):
        '''Bridge per session for a given call using the argument spec
        provided in `count2bridgeargs`. If the value for a given count is
        `proxy` then simply proxy the session to the initial request uri
        destination.
        '''
        call = sess.call
        self.call2entries[call] += 1
        args = self.count2bridgeargs.get(self.call2entries[call])
        if args == 'proxy':  # proxy to dest using request uri
            sess.bridge()
        elif args:  # a dict of kwargs to pass to the bridge cmd
            sess.bridge(**args)

    @event_callback('CHANNEL_BRIDGE')
    def on_bridge(self, sess):
        self.log.debug("Bridged aleg session '{}' to bleg session '{}'"
                       .format(sess.uuid, sess['Bridge-B-Unique-ID']))
