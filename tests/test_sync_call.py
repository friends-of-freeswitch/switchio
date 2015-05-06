# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Tests for synchronous call helper
"""
import time
from switchy import sync_caller


def test_toneplay(fsip):
    '''Test the synchronous caller with a simple toneplay
    '''
    with sync_caller(fsip) as caller:
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
