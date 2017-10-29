# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Tests for core components
'''
from __future__ import division
import sys
import time
import pytest
from pprint import pformat
from switchio import utils, connection


@pytest.fixture
def ael(el):
    """An event listener (el) with active event loop
    Unsubscribe the listener from verbose updates.
    """
    assert not el.connected()
    # avoid latency caused by update events
    el.unsubscribe("CALL_UPDATE")
    el.connect()
    el.start()
    assert el.connected()
    yield el
    el.disconnect()


def bridge2dest_callback(sess):
    if sess['Call-Direction'] == 'inbound':
        sess.bridge(dest_url=sess['variable_sip_req_uri'])


DPS = [bridge2dest_callback]
IDS = ['callback']


if utils.py35:
    import asyncio
    from .asyncio_helpers import *
    DPS.append(bridge2dest_coroutine)
    IDS.append('coroutine')


@pytest.fixture(params=DPS, ids=IDS)
def proxy_dp(request, ael, client):
    """Provision listener with a 'proxy' dialplan app
    """
    routine = request.param

    ev = "CHANNEL_PARK"  # no sess.answer() is ever called

    if utils.py35 and asyncio.iscoroutinefunction(routine):
        # add a proxy coroutine to provide the dialplan
        ael.event_loop.add_coroutine(ev, 'default', routine)
        assert routine in ael.event_loop.coroutines['default'][ev]
    else:
        # add a proxy callback to provide the dialplan
        ael.event_loop.add_callback(ev, 'default', routine)
        assert routine in ael.event_loop.callbacks['default'][ev]

    # attempt to add measurement collection
    try:
        from switchio.apps.measure import CDR
    except ImportError:
        print("WARNING: numpy measurements not available")
    else:
        client.connect()
        client.listener = ael
        # assigning a listener overrides it's call lookup var so restore it
        client.listener.call_tracking_header = 'variable_call_uuid'
        # insert the `CDR` app
        assert 'default' == client.load_app(CDR, on_value="default")
        app = client.apps.default['CDR']
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
def checkcalls(scenario, ael, travis):
    """Return a function that can be used to make calls and check that call
    counting is fast and correct.
    """
    def inner(rate=1, limit=1, duration=3, call_count=None, sleep=1.05):
        # configure cmds
        scenario.rate = rate
        scenario.limit = limit
        scenario.call_count = call_count or limit
        scenario.pause_duration = int(duration * 1000)
        scenario.recv_timeout = scenario.pause_duration + 5000

        scenario.log.info(
            "SIPp cmds: {}".format(pformat(scenario.cmditems()))
        )

        if travis:
            sleep += 0.2
        try:
            scenario(block=False)

            # wait for events to arrive and be processed
            start = time.time()
            msg = "Wasn't quite fast enough to track {} cps".format(rate)
            while ael.count_calls() != limit:
                time.sleep(0.0001)
            else:
                assert ael.count_calls() == limit, msg
                diff = time.time() - start
                assert diff < sleep, msg

            ael.log.info("Call tracking took {} seconds".format(diff))

            time.sleep(duration + sleep)
            assert ael.count_calls() == 0

            if hasattr(ael, 'call_times'):  # check call_times tracking
                assert len(ael.call_times.storer.data) == limit
        finally:
            scenario.finalize()

    return inner


class TestListener:
    def test_startup(self, el):
        '''verify internal connections and listener startup
        '''
        pytest.raises(utils.ConfigurationError, el.start)
        el.connect()
        assert el.connected()

        # verify event loop thread
        el.start()
        assert el.is_alive()
        pytest.raises(utils.ConfigurationError, el.connect)

    @pytest.mark.skipif(
        sys.version_info < (3,0),
        reason="SWIG sucks",
    )
    def test_unreachable_host(self, el, fshost):
        # TODO: test the invalid password / ACL cases
        octets = fshost.split('.')
        addr = '.'.join(octets[:-1] + ['254'])
        with pytest.raises(connection.ConnectionError):
            el.connect(host=addr)

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
        '''test event loop unsubscribe for event type
        '''
        el = el.event_loop
        ev = "CALL_UPDATE"
        default_handlers = dict(el._handlers)
        # updates are too slow so remove them for our test set
        assert el.unsubscribe(ev)
        assert ev not in el._handlers
        # unsubscribing for now non-extant handler
        assert not el.unsubscribe(ev)
        assert ev in el._unsub
        assert ev not in el._rx_con._sub

        # manually reset unsubscriptions
        el._unsub = ()
        el._handlers = default_handlers

        # not allowed after connect
        el.connect()
        with pytest.raises(utils.ConfigurationError):
            assert el.unsubscribe(ev)

    @pytest.mark.skipif(
        sys.version_info >= (3, 5),
        reason="No auto-reconnect support without coroutines"
    )
    def test_reconnect(self, el):
        el.connect()
        con = el._tx_con
        assert con.connected()
        assert el.connected()
        el.start()
        # trigger server disconnect event
        con.api('reload mod_event_socket')
        while con.connected():
            time.sleep(0.01)

        while not con.connected():
            time.sleep(0.01)
        # con.protocol.sendrecv('exit')
        # ensure connections were brought back up
        assert con.connected()
        assert el.connected()
        e = con.api('status')
        assert e
        assert con.connected()

    def test_call(self, ael, proxy_dp, checkcalls):
        """Test a simple call (a pair of sessions) through FreeSWITCH
        """
        checkcalls(duration=3, sleep=1.3)

    def test_cb_err(self, ael, proxy_dp, checkcalls):
        """Verify that the callback chain is never halted due to a single
        callback's error
        """
        var = [None]

        def throw_err(sess):
            raise Exception("Callback failed on purpose")

        def set_var(sess):
            var[0] = 'yay'

        ael.event_loop.add_callback('CHANNEL_CREATE', 'default', throw_err)
        ael.event_loop.add_callback('CHANNEL_CREATE', 'default', set_var)

        checkcalls(duration=3, sleep=1.3)
        # ensure callback chain wasn't halted
        assert var

    @pytest.mark.usefixtures('load_limits')
    def test_track_cps(self, proxy_dp, checkcalls, cps):
        '''load fs with up to 250 cps and test that we're fast enough
        to track all the created session within a 1 sec period

        Note:
        this test may fail intermittently as it depends on the
        speed of the fs server under test
        '''
        checkcalls(rate=cps, limit=cps, call_count=cps, duration=4)

    @pytest.mark.usefixtures('load_limits')
    def test_track_1kcapacity(self, proxy_dp, checkcalls, cps):
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
        from switchio.apps.players import TonePlay
        from switchio.apps.bert import Bert
        from switchio.marks import get_callbacks, event_callback
        from switchio import utils
        with pytest.raises(AttributeError):
            # need an listener assigned first
            client.load_app(TonePlay)
        client.listener = el  # assign listener manually
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
        cbmap = client.listener.event_loop.callbacks[app.cid]
        for evname, cbtype, obj in get_callbacks(app):
            assert evname in cbmap
            reg_cb = cbmap[evname][0]
            # WTF?? 'is' doesn't work on methods?
            assert obj == reg_cb
            # check methods are bound to the same instance
            assert obj.__self__ is reg_cb.__self__

        # add a 2nd app
        # (Bert adds event handlers so a `connect` is necessary)
        client.connect()
        client.listener.connect()
        bid = client.load_app(Bert)

        # verify unload
        client.unload_app(app.cid)
        assert app.cid not in client._apps
        with pytest.raises(KeyError):
            client.listener.event_loop.callbacks[app.cid]

        # Bert should still be there
        assert bid in client._apps
        cbs = client.listener.event_loop.callbacks[
            client.apps.Bert['Bert'].cid]
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
        assert len(client.listener.event_loop.callbacks[bid]) == cbcount

    def test_commands(self, client):
        from switchio.utils import APIError
        from switchio.connection import ConnectionError
        # unconnected attempt
        with pytest.raises(ConnectionError):
            client.cmd('doggy')
        client.connect()
        # bad command
        with pytest.raises(APIError):
            client.cmd('doggy')
        assert client.cmd('status')
