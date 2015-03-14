# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Originator testing

.. note::
    these tests assume that the switchy dialplan has been set for the
    `external` profile's context.
'''
import pytest
import time
import socket
from switchy.apps import dtmf
from switchy import get_originator


@pytest.yield_fixture
def get_orig(request, fshost):
    '''Deliver an `Originator` app which drives a single
    FreeSWITCH slave process.
    '''
    apps = request.node.get_marker('apps')
    ip = socket.gethostbyname(socket.getfqdn(fshost))
    orig = get_originator(ip, apps=apps.kwargs.values())

    def conf_orig(userpart, port=5080, limit=1, rate=1, offer=1):
        # each slave profile should call originate calls to itself
        # to avoid dependency on another server
        orig.pool.evals(
            ("""client.set_orig_cmd('{}@{}:{}'.format(
             userpart, client.server, port), app_name='park')"""),
            userpart=userpart,
            port=port,
        )
        # dut should provide these values based on hw resources
        orig.limit = limit
        orig.rate = rate
        orig.max_offered = offer
        return orig
    yield conf_orig
    orig.shutdown()


@pytest.mark.apps(dtmf=dtmf.DtmfChecker)
def test_dtmf_passthrough(get_orig):
    '''Test the dtmf app in coordination with the originator
    '''
    orig = get_orig('doggy', offer=1)
    orig.duration = 0
    orig.start()
    checker = orig.pool.clients[0].apps.DtmfChecker
    time.sleep(checker.total_time + 1)
    orig.stop()
    assert not any(orig.pool.evals('client.apps.DtmfChecker.incomplete'))
    assert not any(orig.pool.evals('client.apps.DtmfChecker.failed'))
    assert orig.state == "STOPPED"
