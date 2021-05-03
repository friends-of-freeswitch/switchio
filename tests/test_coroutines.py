"""
Helpers for testing py3.5+ ``asyncio`` functionality.

This module is mostly to avoid syntax errors in modules still used for
py2.7 testing.
"""
import pytest
import asyncio
import time
from switchio import sync_caller
from switchio import coroutine


def test_coro_cancel(fsip):
    """Verify that if a call never receives an event which is being
    waited that the waiting coroutine is cancelled at call hangup.
    """
    class MyApp:
        @coroutine("CHANNEL_CREATE")
        async def wait_on_bridge(self, sess):
            # should never arrive since we don't subscribe for the event type
            if sess.is_inbound():
                sess.answer()
                await sess.recv("CHANNEL_ANSWER")
                await sess.recv("CHANNEL_BRIDGE")

    with sync_caller(fsip, apps={"MyApp": MyApp}) as caller:
        # have the external prof call itself by default
        assert 'MyApp' in caller.app_names
        sess, waitfor = caller(
            "doggy@{}:{}".format(caller.client.host, 5080),
            'MyApp',
            timeout=3,
        )
        assert sess.is_outbound()
        callee = sess.call.get_peer(sess)
        callee_futs = callee._futures
        assert callee_futs  # answer fut should be inserted
        time.sleep(0.1)  # wait for answer
        # answer future should be consumed already
        assert not callee_futs.get('CHANNEL_ANSWER', None)
        br_fut = callee_futs['CHANNEL_BRIDGE']
        assert not br_fut.done()
        time.sleep(0.1)
        # ensure our coroutine has been scheduled
        task = callee.tasks[br_fut][0]
        el = caller.client.listener
        assert task in el.event_loop.get_tasks()

        sess.hangup()
        time.sleep(0.1)  # wait for hangup
        assert br_fut.cancelled()
        assert not callee._futures  # should be popped by done callback
        assert el.count_calls() == 0


def test_coro_timeout(fsip):
    """Verify that if a call never receives an event which is being
    waited that the waiting coroutine is cancelled at call hangup.
    """
    class MyApp:
        @coroutine("CHANNEL_CREATE")
        async def timeout_on_hangup(self, sess):
            # should never arrive since we don't subscribe for the event type
            if sess.is_inbound():
                await sess.answer()
                sess.vars['answered'] = True
                await sess.recv("CHANNEL_HANGUP", timeout=1)

    with sync_caller(fsip, apps={"MyApp": MyApp}) as caller:
        # have the external prof call itself by default
        assert 'MyApp' in caller.app_names
        sess, waitfor = caller(
            "doggy@{}:{}".format(caller.client.host, 5080),
            'MyApp',
            timeout=3,
        )
        assert sess.is_outbound()
        callee = sess.call.get_peer(sess)
        callee_futs = callee._futures
        waitfor(callee, 'answered', timeout=0.2)
        # answer future should be popped
        assert not callee_futs.get('CHANNEL_ANSWER')
        hangup_fut = callee_futs.get('CHANNEL_HANGUP')
        assert hangup_fut
        time.sleep(1)  # wait for timeout
        task = callee.tasks.pop(hangup_fut)[0]
        assert task.done()
        with pytest.raises(asyncio.TimeoutError):
            task.result()


@pytest.mark.parametrize('sleep', [2, 5])
def test_simplest_flow(fssock, scenario, client, ael, sleep):
    """Verify that a coroutine can satisfy SIPp's simplest call flow.

    Additionally, verify that when calls are not answered and left in the park
    state they time out and are rejected after 3 seconds (according to the CI
    dialplan).
    """
    class MyApp:
        @coroutine(
            "CHANNEL_PARK",
            subscribe=('PLAYBACK_STOP', 'PLAYBACK_START')
        )
        async def answer_play_hangup(self, sess):
            await asyncio.sleep(sleep)
            await sess.answer()
            # non-blocking
            sess.playback(
                'en/us/callie/ivr/8000/ivr-founder_of_freesource.wav')
            await sess.recv("PLAYBACK_START")
            await sess.recv("CHANNEL_HANGUP")
            # XXX: seems the playback isn't stopping on its own? - the
            # hangup does it though...
            # sess.breakmedia()
            await sess.recv("PLAYBACK_STOP")
            await sess.recv("CHANNEL_HANGUP_COMPLETE")

    client.connect()
    client.listener = ael
    # assigning a listener overrides it's call lookup var so restore it
    client.listener.call_tracking_header = 'variable_call_uuid'
    assert 'default' == client.load_app(MyApp, on_value="default")

    uac = scenario.prepare()[1]
    uac.proxyaddr = None
    uac.destaddr = fssock
    uac.pause_duration = 6000

    # make the call
    if sleep > 3:
        # XML dialplan's `park_timeout` should reject the call
        with pytest.raises(RuntimeError):
            uac()
    else:
        # call should be hung up by this UAC
        uac()
