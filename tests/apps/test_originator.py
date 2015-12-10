# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
`Originator` testing

.. note::
    these tests assume that the `external` sip profile's context
    has been assigned to the switchy dialplan.
'''
from __future__ import division
import pytest
import time
import math
from switchy.apps import dtmf, players
from switchy import get_originator


@pytest.yield_fixture
def get_orig(request, fsip):
    '''Deliver an `Originator` app which drives a single
    FreeSWITCH slave process.
    '''
    origs = []

    def factory(userpart, port=5080, limit=1, rate=1, offer=1, **kwargs):
        orig = get_originator(
            fsip,
            limit=limit,
            rate=rate,
            max_offered=offer,
            **kwargs
        )

        # each slave profile should call originate calls to itself
        # to avoid dependency on another server
        orig.pool.evals(
            ("""client.set_orig_cmd('{}@{}:{}'.format(
             userpart, client.server, port))"""),
            userpart=userpart,
            port=port,
        )
        origs.append(orig)
        return orig

    yield factory
    for orig in origs:
        orig.shutdown()


def test_rep_fields(get_orig):
    """Test replacement fields within originate commands
    """
    ret = {'field': 'kitty'}
    orig = get_orig(
        '{field}',
        apps=[players.TonePlay],
        rep_fields_func=lambda: ret
    )
    orig.duration = 0  # don't auto-hangup
    # check userpart passthrough
    assert 'sofia/external/{field}' in orig.originate_cmd[0]
    assert orig.rep_fields_func() == ret

    # verify invalid field causes failure
    orig.rep_fields_func = lambda: {'invalidname': 'kitty'}
    orig.start()
    time.sleep(0.05)
    # burst loop thread should fail due to missing 'field' kwarg to str.format
    assert orig.stopped()

    # verify field replacement func
    client = orig.pool.clients[0]
    listener = orig.pool.listeners[0]
    # set dest url and call associating xheader to our replaceable field
    ident = "{}@{}:{}".format('doggy', client.host, 5080)
    client.set_orig_cmd('{field}', xheaders={client.call_id_var: "{field}"})
    orig.rep_fields_func = lambda: {'field': ident}
    orig.max_offered += 1
    orig.start()
    time.sleep(0.05)
    assert ident in listener.calls  # since we replaced the call id xheader
    listener.calls[ident].hangup()
    time.sleep(0.05)
    assert orig.count_calls() == 0


def test_dtmf_passthrough(get_orig):
    '''Test the dtmf app in coordination with the originator
    '''
    orig = get_orig('doggy', offer=1, apps=(dtmf.DtmfChecker,))
    orig.duration = 0
    orig.start()
    checker = orig.pool.clients[0].apps.DtmfChecker['DtmfChecker']
    time.sleep(checker.total_time + 1)
    orig.stop()
    assert not any(
        orig.pool.evals("client.apps.DtmfChecker['DtmfChecker'].incomplete"))
    assert not any(
        orig.pool.evals("client.apps.DtmfChecker['DtmfChecker'].failed"))
    assert orig.state == "STOPPED"


def test_convo_sim(get_orig):
    """Test the `PlayRec` app when used for a load test with the `Originator`
    """
    recs = []

    def count(recinfo):
        recs.append(recinfo)

    orig = get_orig(
        'doggy',
        apps=[
            (players.PlayRec,
             {'rec_stereo': True,
              'callback': count})
        ]
    )
    # manual app reference retrieval
    playrec = orig.pool.nodes[0].client.apps.PlayRec['PlayRec']

    # verify dynamic load settings modify playrec settings
    orig.rate = 20
    orig.limit = orig.max_offered = 100
    playrec.rec_period = 2.0
    assert playrec.iterations * playrec.clip_length + playrec.tail == orig.duration

    orig.start()
    # ensure calls are set up fast enough
    start = time.time()
    time.sleep(float(orig.limit / orig.rate) + 1.0)
    stop = time.time()
    assert orig.pool.count_calls() == orig.limit

    # wait for all calls to end
    while not orig.stopped() or orig.pool.count_calls():
        time.sleep(1)

    # ensure number of calls recorded matches the rec period
    assert float(len(recs)) == math.floor((stop - start)/ playrec.rec_period)
