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
        caller.apps.PlayRec.sim_convo = True
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
