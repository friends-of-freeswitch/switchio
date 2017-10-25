"""
Helpers for testing py3.5+ ``asyncio`` functionality.

This module is mostly to avoid syntax errors in modules still used for
py2.7 testing.
"""


async def bridge2dest_coroutine(sess):
    '''Bridge to the dest specified in the req uri
    '''
    if sess['Call-Direction'] == 'inbound':
        sess.bridge(dest_url=sess['variable_sip_req_uri'])
        event = await sess.recv('CHANNEL_ANSWER')
        assert event['Event-Name'] == 'CHANNEL_ANSWER'
