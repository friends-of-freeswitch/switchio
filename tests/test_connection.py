# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Test ESL protocol and connection wrappers
'''
import os
import asyncio
import pytest
import switchio
from switchio.connection import get_connection
from switchio.protocol import InboundProtocol
from switchio import utils


@pytest.fixture(scope='module')
def loop():
    return asyncio.new_event_loop()


@pytest.fixture
def con(fshost, loop):
    con = get_connection(fshost, loop=loop)
    yield con
    con.disconnect()
    pending = utils.all_tasks(loop)
    if pending:
        for task in pending:
            if not task.done():
                task.cancel()
        loop.run_until_complete(asyncio.wait(pending, loop=loop))


@pytest.mark.parametrize(
    'password, expect_auth',
    [('doggy', False), ('ClueCon', True)],
    ids=lambda item: item,
)
def test_connect(con, password, expect_auth):
    """Connection basics.
    """
    if expect_auth:
        con.connect(password=password)
        assert con.protocol.authenticated()
    else:
        with pytest.raises(switchio.ConnectionError):
            con.connect(password=password)
        assert not con.protocol.authenticated()


def test_disconnect(con, loop):
    con.connect()
    assert con.connected()
    assert con.protocol.authenticated()
    con.disconnect()
    assert not con.connected()
    assert not con.protocol.authenticated()


@pytest.fixture
def get_event_stream():

    def read_stream(filename):
        dirname = os.path.dirname
        filepath = os.path.abspath(
            os.path.join(
                dirname(os.path.realpath(__file__)),
                'data/{}'.format(filename)
            )
        )
        with open(filepath, 'r') as evstream:
            return evstream.read().encode()

    return read_stream


def test_parse_event_stream1(con, get_event_stream):
    """Assert event packet/chunk parsing is correct corresponding
    to our sample file.
    """
    event_stream = get_event_stream('eventstream.txt')
    con.connect()
    events = con.protocol.data_received(event_stream)
    assert len(events[0]) == 1
    assert events[1]['Reply-Text'] == '+OK accepted'
    assert events[2]['Reply-Text'] == '+OK bye'
    assert events[3]['Body']

    # std state update
    assert events[4]['Channel-State'] == 'CS_INIT'
    # multiline value
    ev4 = events[4]
    first = 'v=0'
    assert ev4['variable_switch_r_sdp'][:len(first)] == first
    last = 'a=rtcp:4017 IN IP4 172.16.7.70'
    assert ev4['variable_switch_r_sdp'][-1-len(last):-1] == last


def test_parse_segmented_event_stream(get_event_stream):
    """Verify segmented packets are processed correctly.
    """
    prot = InboundProtocol(None, None, None)
    first, second, third, fourth = get_event_stream(
        'eventstream2.txt').split(b'--')
    events = prot.data_received(first)
    assert len(events) == 1
    assert events[0]['Job-UUID']
    assert prot._segmented[1] == 1048  # len of bytes after splitting on '--'
    assert len(prot._segmented[0]) == 2

    events = prot.data_received(second)
    assert events[0]['Body'] == '+OK 8de782e0-83c9-11e7-af1b-001500e3e25c\n'
    assert events[1]['Event-Name'] == 'CHANNEL_PARK'

    assert prot._segmented[2] == 'Event'
    # import pdb; pdb.set_trace()
    events3 = prot.data_received(third)
    assert len(events3) == 1
    assert events3[0]['Event-Name'] == 'BACKGROUND_JOB'

    assert prot._segmented[2]
    assert not prot._segmented[0]
    assert prot._segmented[1] == 0
    events4 = prot.data_received(fourth)
    assert not any(prot._segmented)
    assert len(events4) == 1
    patt = '+OK Job-UUID'
    assert events4[0]['Reply-Text'][:len(patt)] == patt
