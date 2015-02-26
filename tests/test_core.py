# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab
# Copyright (C) 2013  Sangoma Technologies Corp.
# All Rights Reserved.
# Author(s)
# Tyler Goodlet <tgoodlet@sangoma.com>
from __future__ import division
import time
import pytest
from ..utils import ConfigurationError


@pytest.yield_fixture
def scenario(request, fssock):
    '''provision and return a SIPp scenario with the
    remote proxy set to the current fs server
    '''
    try:
        from sangoma.tools import sipp
    except ImportError:
        pytest.skip("python sipp module not found?")
    s = sipp.Scenario()
    # first hop should be fs server
    s.proxy = fssock
    # NOTE: you must add a park extension to your default dialplan!
    s.agents.uac.inputs.username_uri = 'park'
    yield s
    assert s.collect_results()
    s.cleanup()


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
def proxy_dp(ael):
    """Provision listener with a 'proxy' dialplan app
    """
    # define a chan park callback
    def bridge2dest(sess):
        '''bridge to the dest specified in the req uri
        '''
        if sess['Call-Direction'] == 'inbound':
            sess.bridge(
                dest_url="${sip_req_user}@${sip_req_host}:${sip_req_port}")
            # print(sess.show())

    ev = "CHANNEL_PARK"
    # add a failover callback to provide the dialplan
    ael.add_callback(ev, 'default', bridge2dest)
    # ensure callback was registered
    assert bridge2dest in ael.consumers['default'][ev]

    # attempt to add measurement collection
    try:
        from ..apps.measure import Metrics
    except ImportError:
        print("WARNING: numpy measurements not available")
    else:
        from .. import marks
        # manually insert the metrics app
        metrics = Metrics(listener=ael)
        for ev_type, cb_type, obj in marks.get_callbacks(metrics):
            if cb_type == 'callback':
                assert ael.add_callback(ev_type, 'default', obj)
                assert obj in ael.consumers['default']['CHANNEL_HANGUP']
        ael.metrics = metrics
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
        print("[{1}] call count is '{0}'".format(calls, datetime.now()))
        calls = el.count_calls()


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

    def test_call(self, ael, proxy_dp, scenario):
        duration = 3
        scenario.call_load = 1
        scenario.global_settings.pause_duration = int(duration * 1000)
        # scenario.show_cmds()
        scenario.run(block=False)  # non-blocking
        time.sleep(1.3)  # we can track up to around 250cps (very rough)
        assert ael.count_calls() == 1
        time.sleep(duration + 0.5)
        assert ael.count_calls() == 0

    def test_track_cps(self, proxy_dp, ael, scenario, cps):
        '''load fs with up to 250 cps and test that we're fast enough
        to track all the created session within a 1 sec period

        Note:
        this test may fail intermittently as it depends on the
        speed of the fs server under test
        '''
        duration = 4
        scenario.global_settings.pause_duration = int(duration * 1000)
        scenario.call_load = cps
        scenario.run(block=False)  # non-blocking

        # wait for events to arrive and be processed
        time.sleep(1.1)
        msg = "Wasn't quite fast enough to track {} cps".format(cps)
        assert ael.count_calls() == cps, msg
        time.sleep(duration + 1.05)
        assert ael.count_calls() == 0
        if hasattr(ael, 'metrics'):
            assert ael.metrics.array.size == cps

    def test_track_1kcapacity(self, ael, proxy_dp, scenario, cps):
        '''load fs with up to 1000 simultaneous calls
        and test we (are fast enough to) track all the created sessions

        Note:
        this tes may fail intermittently as it depends on the
        speed of the fs server under test
        '''
        limit = 1000
        duration = limit / cps + 1  # h = E/lambda (erlang formula)
        scenario.global_settings.pause_duration = int(duration * 1000)
        scenario.call_load = cps, limit, limit
        scenario.run(block=False)  # non-blocking

        # wait for events to arrive and be processed
        time.sleep(duration)
        assert ael.count_calls() == limit
        time.sleep(duration + 1.5)
        assert ael.count_calls() == 0
        if hasattr(ael, 'metrics'):
            assert ael.metrics.array.size == limit


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
        from ..apps.test import TonePlay
        from ..apps.bert import Bert
        from ..marks import get_callbacks, event_callback
        from .. import utils
        with pytest.raises(AttributeError):
            client.load_app(TonePlay)
        client.listener = el  # assign listener manually
        assert client.listener is el

        # loading
        client.load_app(TonePlay)
        name = utils.get_name(TonePlay)
        assert name in client._apps
        # app should be an instance of the app type
        app = client._apps[name]
        assert isinstance(app, TonePlay)
        # reloading the same app shouldn't overwrite the original
        client.load_app(TonePlay)
        assert app is client._apps[name]

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
        client.unload_app(TonePlay)
        assert TonePlay not in client._apps
        with pytest.raises(KeyError):
            client.listener.consumers[app.cid]

        # 2nd should still be there
        assert utils.get_name(Bert) in client._apps
        cbs = client.listener.consumers[client.apps.Bert.cid]
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

            class noncb(object):
                pass

            # non-function marked obj
            fack = event_callback('CHANNEL_PARK')(noncb)

        with pytest.raises(TypeError):
            client.load_app(DumbApp, ident=bid)
        name = utils.get_name(DumbApp)
        assert name not in client._apps
        # Bert cbs should still be active
        assert len(client.listener.consumers[bid]) == cbcount

    def test_commands(self, client):
        from ..utils import CommandError
        with pytest.raises(CommandError):
            client.api('doggy')
        assert client.api('status')
