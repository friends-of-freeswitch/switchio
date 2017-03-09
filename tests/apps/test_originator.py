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
import time
import math
from switchy.apps import dtmf, players


def test_dialer_state(get_orig):
    """Verify dialer state changes based on its API.
    """
    dialer = get_orig('you', offer=float('inf'))
    dialer.load_app(players.TonePlay)
    dialer.duration = 0  # don't auto-hangup

    # ensure intial state interface
    assert dialer.check_state("INITIAL")

    # verify initial internal event states
    assert not dialer._start.is_set()
    assert not dialer._burst.is_set()
    assert not dialer._exit.is_set()

    dialer.start()
    time.sleep(0.3)
    assert not dialer._start.is_set()
    assert not dialer.stopped()
    assert dialer._burst.is_set()
    assert dialer.check_state("ORIGINATING")

    dialer.hupall()
    dialer.waitforstate('STOPPED', timeout=5)
    assert dialer.check_state("STOPPED")
    assert dialer.stopped()
    assert not dialer._start.is_set()
    assert not dialer._burst.is_set()


def test_rep_fields(get_orig):
    """Test replacement fields within originate commands
    """
    ret = {'field': 'kitty'}
    orig = get_orig('{field}', rep_fields_func=lambda: ret)
    orig.load_app(players.TonePlay)
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
    client.set_orig_cmd('{field}',
                        xheaders={client.call_tracking_header: "{field}"})
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
    orig = get_orig('doggy', offer=1)
    orig.load_app(dtmf.DtmfChecker)
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

    orig = get_orig('doggy')
    orig.load_app(
        players.PlayRec,
        ppkwargs={
            'rec_stereo': True,
            'callback': count,
        }
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
    orig.waitwhile()
    # ensure number of calls recorded matches the rec period
    assert float(len(recs)) == math.floor((stop - start) / playrec.rec_period)
