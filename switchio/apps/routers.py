# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Routing apps
"""
import re
import asyncio
from functools import partial
from collections import OrderedDict
from collections import Counter
from .. import utils
from ..marks import coroutine, callback, extend_attr_list
from ..apps import app


@app
class Proxier(object):
    """Proxy all inbound calls to the destination specified in the SIP
    Request-URI.

    .. note::
        This is meant as a simple example for testing. If you want to build
        a routing system see the `Router` app below.
    """
    @callback('CHANNEL_PARK')
    def on_park(self, sess):
        if sess.is_inbound():
            # by default bridges to sess['variable_sip_req_uri']
            sess.bridge()


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

    @callback("CHANNEL_PARK")
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

    @callback('CHANNEL_BRIDGE')
    def on_bridge(self, sess):
        self.log.debug("Bridged aleg session '{}' to bleg session '{}'"
                       .format(sess.uuid, sess['Bridge-B-Unique-ID']))


class PatternRegistrar(object):
    """A `flask`-like pattern to callback registrar.

    Allows for registering callback functions (via decorators) which will be
    delivered when `PatterCaller.iter_matches()` is invoked with a matching
    value.
    """
    def __init__(self):
        self.regex2funcs = OrderedDict()

    def update(self, other):
        """Update local registered functions from another registrar.
        """
        self.regex2funcs.update(other.regex2funcs)

    def __call__(self, pattern, field='Caller-Destination-Number', **kwargs):
        """Decorator interface allowing you to register callback or coroutine
        functions with regex patterns and kwargs. When `iter_matches` is
        called with a mapping, any callable registered with a matching regex
        pattern will be delivered as a partial.
        """
        def inner(func):
            assert asyncio.iscoroutinefunction(func), 'Not a coroutine'
            self.regex2funcs.setdefault(
                (pattern, field), []).append((func, kwargs))
            return func

        return inner

    def iter_matches(self, fields, **kwargs):
        """Perform registered order lookup for all functions with a matching
        pattern. Each function is partially applied with it's matched value as
        an argument and any kwargs provided here. Any kwargs provided at
        registration are also forwarded.
        """
        for (patt, field), funcitems in self.regex2funcs.items():
            value = fields.get(field)
            if value:
                match = re.match(patt, value)
                if match:
                    for func, defaults in funcitems:
                        if kwargs:
                            defaults.update(kwargs)
                        yield partial(func, match=match, **defaults)


@app
class Router(object):
    '''Route sessions using registered callback functions (decorated as
    "routes") which are pattern matched based on selected channel variable
    contents.

    Requires that the handling SIP profile had been configured to use the
    'switchio' dialplan context or at the very least a context which contains a
    park action extension.
    '''
    # Signal a routing halt
    class StopRouting(Exception):
        """Signal a router to discontinue execution.
        """

    def __init__(self, guards=None, reject_on_guard=True, subscribe=()):
        self.guards = guards or {}
        self.guard = reject_on_guard
        # subscribe for any additional event types requested by the user
        extend_attr_list(self.on_park, 'switchio_events_sub', subscribe)
        self.route = PatternRegistrar()

    def prepost(self, pool):
        self.pool = pool
        self.log = utils.get_logger(
            utils.pstr(self, pool.evals('listener.host'))
        )

    @coroutine("CHANNEL_PARK")
    async def on_park(self, sess):
        handled = False
        if not all(sess[key] == val for key, val in self.guards.items()):
            self.log.warning("Session with id {} did not pass guards"
                             .format(sess.uuid))
        else:
            for func in self.route.iter_matches(sess, sess=sess, router=self):
                handled = True  # at least one match
                try:
                    self.log.debug(
                        "Matched '{.string}' to route '{.__name__}'"
                        .format(func.keywords['match'], func.func))

                    await func()
                except self.StopRouting:
                    self.log.info(
                        "Routing was halted at {} at match '{}' for session {}"
                        .format(func, func.keywords['match'].string, sess.uuid)
                    )
                    break
                except Exception:
                    self.log.exception(
                        "Failed to exec {} on match '{.string}' for session {}"
                        .format(func.func, func.keywords['match'], sess.uuid)
                    )
        if not handled and self.guard:
            self.log.warning("Rejecting session {}".format(sess.uuid))
            await sess.hangup('NO_ROUTE_DESTINATION')

    @staticmethod
    async def bridge(
        sess, match, router, dest_url=None, out_profile=None,
        gateway=None, proxy=None
    ):
        """A handy generic bridging function.
        """
        sess.bridge(
            # bridge back out the same profile if not specified
            # (the default action taken by bridge)
            profile=out_profile,
            gateway=gateway,
            dest_url=dest_url,  # default is ${sip_req_uri}
            proxy=proxy,
        )
