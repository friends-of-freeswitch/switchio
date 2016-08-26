# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Tests for routing apps.

Checklist:
- verify route order
- guards block
- raise StopRouting
- multiple matches
- multiple routers
x cluster support
x load test over multiple nodes is fast
'''
import pytest
import time
import contextlib
from switchy import Service
from switchy.apps.routers import Router
from collections import defaultdict
pysipp = pytest.importorskip("pysipp")


@pytest.fixture
def router(fshost):
    """An inbound router which processes sessions from the `external`
    SIP profile.
    """
    return Router(guards={
        'Caller-Direction': 'inbound',
        'variable_sofia_profile_name': 'external'
    })


@pytest.fixture
def service(fshosts, router):
    """A switchy routing service.
    """
    s = Service(fshosts)
    yield s
    s.stop()


@contextlib.contextmanager
def dial_all(scenarios, did, hosts, expect=True, **extra_settings):
    """Async dial all FS servers in the test cluster with the given ``did``.
    ``expect`` is a bool determining whether the calls should connect using
    the standard SIPp call flow.
    """
    finalizers = []
    # run all scens async
    for scenario, host in zip(scenarios, hosts):
        if getattr(scenario, 'agents', None):
            scenario.defaults.update(extra_settings)
            scenario.agents['uac'].uri_username = did
        else:  # a client instance
            scenario.uri_username = did

        finalizers.append(scenario(block=False))

    yield scenarios

    # finalize
    for finalize in finalizers:
        if expect is True:
            finalize()
        else:
            if isinstance(expect, list):
                cmd2procs = finalize(raise_exc=False)
                for cmd, proc in cmd2procs.items():
                    rc = proc.returncode
                    assert rc in expect, (
                        "{} for {} was not in expected return codes {}".format(
                            rc, cmd, expect))
                    expect.remove(rc)

            else:  # generic failure
                with pytest.raises(RuntimeError):
                    finalize()


def test_route_order(router):
    """Verify route registration order is maintained.
    """
    @router.route('0', field='did')
    def doggy():
        pass

    @router.route('0', field='did')
    def kitty():
        pass

    @router.route('0', field='did')
    def mousey():
        pass

    assert ['doggy', 'kitty', 'mousey'] == [
        p.func.func_name for p in router.route.iter_matches({'did': '0'})
    ]


def test_guard_block(scenarios, service, router):
    """Verify that if a guard is not satisfied the call is rejected.
    """
    router.guards['variable_sofia_profile_name'] = 'doggy'
    service.apps.load_app(router, app_id='default')
    service.run(block=False)
    assert service.is_alive()
    with dial_all(
        scenarios, 'doggy', router.pool.evals('client.host'), expect=False
    ):
        pass


def test_break_on_true(fs_socks, service, router):
    """raising ``StopRouting`` should halt all further processing.
    """
    did = '101'
    router.sessions = []

    @router.route(did)
    def answer(sess, router, match):
        sess.answer()
        router.sessions.append(sess)
        # prevent the downstream hangup route from executing
        raise router.StopRouting

    @router.route(did)
    def hangup(sess, router, match):
        sess.hangup()

    # start router service
    service.apps.load_app(router, app_id='default')
    service.run(block=False)
    assert service.is_alive()

    clients = []
    for socketaddr in fs_socks:
        client = pysipp.client(destaddr=socketaddr)
        client.pause_duration = 2000
        clients.append(client)

    hosts = router.pool.evals('client.host')

    with dial_all(clients, did, hosts):

        # wait for SIPp start up
        start = time.time()
        while len(router.sessions) < len(hosts) and time.time() - start < 5:
            time.sleep(0.1)

        # verify all sessions are still active and 2nd route was never called
        for sess in router.sessions:
            assert sess.answered and not sess.hungup

    # hangup should come shortly after
    for sess in router.sessions:
        assert sess.hungup


@pytest.mark.parametrize(
    'did, expect', [
        ('bridge', True),  # match first
        (' hangup', [1, 0]),  # match second
        ('none', [1, 0]),  # match nothing
        # match 2 and have FS hangup mid bridge
        ('bridge_hangup', [1, 0]),
    ],
)
def test_routes(scenarios, service, router, did, expect):
    """Test routing based on Request-URI user part patterns.
    """
    called = defaultdict(list)

    # route to the b-leg SIPp UAS
    @router.route('bridge.*', field='Caller-Destination-Number')
    def bridge(sess, match, router):
        sess.bridge()
        called[sess.con.host].append('bridge')

    @router.route('.*hangup')
    def hangup(sess, router, match):
        sess.hangup()
        called[sess.con.host].append('hangup')

    @router.route('reject')
    def reject(sess, router, match):
        sess.respond('407')
        called[sess.con.host].append('reject')

    service.apps.load_app(router, app_id='default')
    service.run(block=False)
    assert service.is_alive()

    defaults = {'pause_duration': 10000} if 'hangup' in did else {}

    with dial_all(
        scenarios, did, router.pool.evals('client.host'),
        expect, **defaults
    ):
        pass

    # verify route paths
    for host, routepath in called.items():
        for i, patt in enumerate(did.split('_')):
            assert routepath[i] == patt


@pytest.mark.parametrize('order, reject, expect', [
    (iter, True, False), (reversed, False, True)])
def test_multiple_routers(scenarios, service, router, order, reject, expect):
    """Test that multiple routers will work cooperatively.
    In this case the second rejects calls due to guarding.
    """
    # first router bridges to the b-leg SIPp UAS
    router.route('bridge.*', field='Caller-Destination-Number')(
        router.bridge)

    router2 = Router({'Caller-Direction': 'doggy'}, reject_on_guard=reject)
    service.apps.load_multi_app(order([router, router2]), app_id='default')
    service.run(block=False)
    assert service.is_alive()

    with dial_all(
        scenarios, 'bridge', router.pool.evals('client.host'), expect=expect
    ):
        pass
