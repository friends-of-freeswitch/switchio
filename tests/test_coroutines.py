"""
Helpers for testing py3.5+ ``asyncio`` functionality.

This module is mostly to avoid syntax errors in modules still used for
py2.7 testing.
"""
import time
from switchio import sync_caller
from switchio import coroutine


def test_cancel_coro(fsip):
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
