# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Tests for core components
'''
from __future__ import division
import time
import pytest
from distutils import spawn
from switchy.utils import ConfigurationError


@pytest.yield_fixture
def scenario(request, fssock):
    '''provision and return a SIPp scenario with the
    remote proxy set to the current fs server
    '''
    sipp = spawn.find_executable('sipp')
    if not sipp:
        pytest.skip("SIPp is required to run call/speed tests")
    import socket
    from helpers import CmdStr, get_runner
    # build command template
    template = (
        '{remote_host}:{remote_port}',
        '-i {local_ip}',
        '-p {local_port}',
        '-recv_timeout {msg_timeout}',
        '-sn {scen_name}',
        '-s {uri_username}',
        '-rsa {proxy}',
        # load settings
        '-d {duration}',
        '-r {rate}',
        '-l {limit}',
        '-m {call_count}'
    )

    # common
    ua = CmdStr(sipp, template)
    ua.local_ip = socket.gethostbyname(socket.getfqdn())
    ua.duration = 10000
    ua.call_count = 1
    ua.limit = 1
    # uas
    uas = ua.copy()
    uas.scen_name = 'uas'
    uas.local_port = 8888
    # uac
    uac = ua.copy()
    uac.scen_name = 'uac'
    uac.local_port = 9999
    uac.remote_host = uas.local_ip
    uac.remote_port = uas.local_port
    # NOTE: you must add a park extension to your default dialplan!
    uac.uri_username = 'park'  # call the park extension
    # first hop should be fs server
    uac.proxy = ':'.join(map(str, fssock))

    runner = get_runner((uas, uac))
    yield runner
    # print output
    for name, (out, err) in runner.results.items():
        print("{} stderr: {}".format(name, err))
    # ensure no failures
    for ua, proc in runner.procs.items():
        # if it's None then sipp procs are probably still alive
        assert proc.returncode == 0


@pytest.yield_fixture
def ael(el):
    """An event listener (el) with active event loop
    Unsubscribe the listener from verbose updates.
    """
    assert not el.connected()
    # avoid latency caused by update events
    el.unsubscribe("CALL_UPDATE")
    el.connect()
    assert not el.is_alive()
    el.start()
    assert el.connected()
    yield el
    el.disconnect()


@pytest.fixture
def proxy_dp(ael, client):
    """Provision listener with a 'proxy' dialplan app
    """
    # define a chan park callback
    def bridge2dest(sess):
        '''bridge to the dest specified in the req uri
        '''
        if sess['Call-Direction'] == 'inbound':
            sess.bridge(dest_url="${sip_req_uri}")

    ev = "CHANNEL_PARK"  # no answer() is ever done...
    # add a failover callback to provide the dialplan
    ael.add_callback(ev, 'default', bridge2dest)
    # ensure callback was registered
    assert bridge2dest in ael.consumers['default'][ev]

    # attempt to add measurement collection
    try:
        from switchy.apps.measure import CallTimes
    except ImportError:
        print("WARNING: numpy measurements not available")
    else:
        client.connect()
        client.listener = ael
        # assigning a listener overrides it's call lookup var so restore it
        client.listener.call_id_var = 'variable_call_uuid'
        # insert the `CallTimes` app
        assert 'default' == client.load_app(CallTimes, on_value="default")
        app = client.apps.default['CallTimes']
        ael.call_times = app
    # sanity
    assert ael.connected()
    assert ael.is_alive()
    return ael


@pytest.fixture
def load_limits(con):
    """Apply sensible load testing limits
    """
    con.api('fsctl loglevel WARNING')
    con.api('fsctl max_sessions 10000')
    con.api('fsctl sps 1000')


def monitor(el):
    """Monitor call count in a loop
    """
    from datetime import datetime
    calls = el.count_calls()
    while calls:
        el.log.info("[{1}] call count is '{0}'".format(calls, datetime.now()))
        calls = el.count_calls()


@pytest.fixture
def checkcalls(proxy_dp, scenario, ael):
    """Return a function that can be used to make calls and check that call
    counting is fast and correct.
    """
    def inner(rate=1, limit=1, duration=3, call_count=None, sleep=1.1):
        # configure cmds
        for ua in scenario.cmds:
            ua.rate = rate
            ua.limit = limit
            ua.call_count = call_count or limit
            ua.duration = int(duration * 1000)
            print("SIPp cmd: {}".format(ua.render()))

        # verify call counting
        with scenario():
            # wait for events to arrive and be processed
            time.sleep(sleep)
            msg = "Wasn't quite fast enough to track {} cps".format(rate)
            assert ael.count_calls() == limit, msg
            time.sleep(duration + 1.05)
            assert ael.count_calls() == 0

        if hasattr(ael, 'call_times'):  # check call_times tracking
            assert len(ael.call_times.storer.data) == limit

    return inner


@pytest.mark.usefixtures('load_limits')
class TestListener:
    def test_startup(self, el):
        '''verify internal connections and listener startup
        '''
        pytest.raises(ConfigurationError, el.start)
        el.connect()
        for name, con in el.iter_cons():
            assert con.connected()

        # verify event loop thread
        el.start()
        assert el.is_alive()
        pytest.raises(ConfigurationError, el.connect)

    def test_disconnect(self, el):
        '''Verify we can disconnect after having started the event loop
        '''
        el.disconnect()  # no-op
        el.connect()
        el.start()
        el.disconnect()
        assert not el.is_alive()
        assert not el.connected()

    def test_unsub(self, el):
        '''test listener unsubscribe for event type
        '''
        ev = "CALL_UPDATE"
        # updates are too slow so remove them for our test set
        assert el.unsubscribe(ev)
        assert ev not in el._handlers
        # unsubscribing for now non-extant handler
        assert not el.unsubscribe(ev)

        # manually reset unsubscriptions
        el._unsub = ()
        el._handlers = el.default_handlers

        # test once connected
        el.connect()
        assert el.unsubscribe(ev)
        assert ev not in el._handlers
        assert ev in el._unsub
        assert ev not in el._rx_con._sub
        assert el.connected()

        # not allowed after start
        el.start()
        with pytest.raises(ConfigurationError):
            assert el.unsubscribe(ev)

    def test_reconnect(self, el, con):
        el.connect()
        assert con.connected()
        el.con = con
        assert el.connected()
        # trigger server disconnect event
        con.api('reload mod_event_socket')
        # ensure connections were brought back up
        assert con.connected()
        assert el.connected()
        e = con.api('status')
        assert e
        assert con.connected()
        # remove connection from listener set
        delattr(el, 'con')

    def test_call(self, checkcalls):
        """Test a simple call (a pair of sessions) through FreeSWITCH
        """
        checkcalls(duration=3, sleep=1.3)

    def test_cb_err(self, ael, checkcalls):
        """Verify that the callback chain is never halted due to a single
        callback's error
        """
        var = [None]

        def throw_err(sess):
            raise Exception("Callback failed on purpose")

        def set_var(sess):
            var[0] = 'yay'

        ael.add_callback('CHANNEL_CREATE', 'default', throw_err)
        ael.add_callback('CHANNEL_CREATE', 'default', set_var)

        checkcalls(duration=3, sleep=1.3)
        # ensure callback chain wasn't halted
        assert var

    def test_track_cps(self, checkcalls, cps):
        '''load fs with up to 250 cps and test that we're fast enough
        to track all the created session within a 1 sec period

        Note:
        this test may fail intermittently as it depends on the
        speed of the fs server under test
        '''
        checkcalls(rate=cps, limit=cps, call_count=cps, duration=4)

    def test_track_1kcapacity(self, checkcalls, cps):
        '''load fs with up to 1000 simultaneous calls
        and test we (are fast enough to) track all the created sessions

        Note:
        this tes may fail intermittently as it depends on the
        speed of the fs server under test
        '''
        limit = 1000
        duration = limit / cps + 1  # h = E/lambda (erlang formula)
        checkcalls(rate=cps, limit=limit, duration=duration, sleep=duration)


class TestClient:
    def test_startup(self, client):
        """Test client provisioning steps
        """
        # client should come with connections set up
        client.connect()
        assert client.connected()
        client.disconnect()
        assert not client.connected()
        client.connect()
        # verify failure when no listener assigned
        with pytest.raises(AttributeError):
            client.listener

    def test_apps(self, client, el):
        """Test app loading, unloading
        """
        from switchy.apps.players import TonePlay
        from switchy.apps.bert import Bert
        from switchy.marks import get_callbacks, event_callback
        from switchy import utils
        with pytest.raises(AttributeError):
            # need an observer assigned first
            client.load_app(TonePlay)
        client.listener = el  # assign observer manually
        assert client.listener is el

        # loading
        client.load_app(TonePlay)
        name = utils.get_name(TonePlay)
        # group id is by default the name of the first app
        assert name in client._apps
        # app should be an instance of the app type
        app = client._apps[name][name]
        assert isinstance(app, TonePlay)

        # reloading the same app is not allowed without specifying
        # a new `on_value` / group id
        with pytest.raises(utils.ConfigurationError):
            client.load_app(TonePlay)
        # load with an alt id
        client.load_app(TonePlay, 'TonePlay2')
        # and therefore shouldn't overwrite the original
        assert app is client._apps[name][name]
        assert app is not client._apps['TonePlay2'][name]

        # check that callbacks are registered with listener
        cbmap = client.listener.consumers[app.cid]
        for evname, cbtype, obj in get_callbacks(app):
            assert evname in cbmap
            reg_cb = cbmap[evname][0]
            # WTF?? 'is' doesn't work on methods?
            assert obj == reg_cb
            # check methods are bound to the same instance
            assert obj.im_self is reg_cb.im_self

        # add a 2nd app
        # (Bert adds event handlers so a `connect` is necessary)
        client.listener.connect()
        bid = client.load_app(Bert)

        # verify unload
        client.unload_app(app.cid)
        assert app.cid not in client._apps
        with pytest.raises(KeyError):
            client.listener.consumers[app.cid]

        # Bert should still be there
        assert bid in client._apps
        cbs = client.listener.consumers[client.apps.Bert['Bert'].cid]
        assert cbs
        cbcount = len(cbs)

        # app reject due to mal-typed cb
        class DumbApp(object):
            @event_callback('CHANNEL_ANSWER')
            def h0(self, sess):
                pass

            @event_callback('CHANNEL_HANGUP')
            def h1(self, sess):
                pass

            # non-function marked obj
            @event_callback('CHANNEL_PARK')
            class noncb(object):
                pass

        with pytest.raises(TypeError):
            client.load_app(DumbApp, ident=bid)
        name = utils.get_name(DumbApp)
        assert name not in client._apps
        assert name not in client.apps.Bert
        # Bert cbs should still be active
        assert len(client.listener.consumers[bid]) == cbcount

    def test_commands(self, client):
        from switchy.utils import CommandError
        from switchy.connection import ConnectionError
        # unconnected attempt
        with pytest.raises(ConnectionError):
            client.api('doggy')
        client.connect()
        # bad command
        with pytest.raises(CommandError):
            client.api('doggy')
        assert client.api('status')
