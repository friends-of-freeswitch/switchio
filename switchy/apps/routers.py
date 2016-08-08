# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Routing apps
"""
from collections import Counter
from .. import utils
from ..marks import event_callback
from ..apps import app


@app
class Bridger(object):
    '''Bridge sessions within a call an arbitrary number of times.
    '''
    def prepost(self):
        self.log = utils.get_logger(self.__class__.__name__)
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


@app
class Router(object):
    '''Route sessions using registered callback functions (decorated as
    "routes") which are pattern matched based on selected channel variable
    contents.

    Requires that the handling SIP profile had been configured to use the
    'switchy' dialplan context or at the very least a context which contains a
    park action extension.
    '''
    # default routes
    route = utils.PatternCaller()

    def __init__(self, guards, use_defaults=True):
        self.guards = guards or {}
        self.route = utils.PatternCaller()
        if use_defaults:
            self.route.update(type(self).route)

    def prepost(self, pool):
        self.host = pool.evals('client.host')
        self.log = utils.get_logger(utils.pstr(self))

    @event_callback("CHANNEL_PARK")
    def on_park(self, sess):
        if all(sess[key] == val for key, val in self.guards.items()):
            self.route.call_matches(sess, sess=sess, router=self)
        else:
            self.log.warn("Session with id {} did not pass guards"
                          .format(sess.uuid))

    @staticmethod
    def bridge2dest(sess, match, router, out_profile=None, gateway=None,
                    proxy=None):
        # if calling in to a registered user bridge appropriately

        # bridge to destination
        sess.bridge(
            # bridge back out the same profile if not specified
            # (the default action taken by bridge)
            profile=out_profile,
            gateway=gateway,
            dest_url=sess['variable_sip_req_uri'],
            proxy=proxy,
        )
