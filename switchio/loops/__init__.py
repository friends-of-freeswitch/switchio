"""
Event loops!
"""
from .. import utils
from .proactor import EventLoop


def get_event_loop(host, port=EventLoop.PORT, auth=EventLoop.AUTH,
                   **kwargs):
    '''Event loop factory. When using python 3.5 + an ``asyncio`` based loop
    is used.
    '''
    return EventLoop(host, port, auth, **kwargs)
