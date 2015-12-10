# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Tests for synchronous call helper
"""
import time
from switchy import sync_caller
from switchy.apps.players import TonePlay, PlayRec


def test_toneplay(fsip):
    '''Test the synchronous caller with a simple toneplay
    '''
    with sync_caller(fsip, apps={"TonePlay": TonePlay}) as caller:
        # have the external prof call itself by default
        assert 'TonePlay' in caller.app_names
        sess, waitfor = caller(
            "doggy@{}:{}".format(caller.client.server, 5080),
            'TonePlay',
            timeout=3,
        )
        assert sess.is_outbound()
        time.sleep(1)
        sess.hangup()
        time.sleep(0.1)
        assert caller.client.listener.count_calls() == 0


def test_playrec(fsip):
    '''Test the synchronous caller with a simulated conversation using the the
    `PlayRec` app. Currently this test does no audio checking but merely verifies
    the callback chain is invoked as expected.
    '''
    with sync_caller(fsip, apps={"PlayRec": PlayRec}) as caller:
        # have the external prof call itself by default
        caller.apps.PlayRec['PlayRec'].rec_rate = 1
        sess, waitfor = caller(
            "doggy@{}:{}".format(caller.client.server, 5080),
            'PlayRec',
            timeout=10,
        )
        waitfor(sess, 'recorded', timeout=15)
        waitfor(sess.call.get_peer(sess), 'recorded', timeout=15)
        assert sess.call.vars['record']
        time.sleep(1)
        assert sess.hungup


def test_alt_call_id_var(fsip):
    '''Test that an alternate `EventListener.call_id_var` (in this case using the
    'Caller-Destination-Number' channel variable) can be used to associate sessions
    into calls.
    '''
    with sync_caller(fsip) as caller:
        # use the destination number as the call association var
        caller.client.listener.call_id_var = 'Caller-Destination-Number'
        dest = 'doggy'
        # have the external prof call itself by default
        sess, waitfor = caller(
            "{}@{}:{}".format(dest, caller.client.server, 5080),
            'TonePlay',  # the default app
            timeout=3,
        )
        assert sess.is_outbound()
        # call should be indexed by the req uri username
        assert dest in caller.client.listener.calls
        call = caller.client.listener.calls[dest]
        time.sleep(1)
        assert call.first is sess
        assert call.last
        call.hangup()
        time.sleep(0.1)
        assert caller.client.listener.count_calls() == 0
