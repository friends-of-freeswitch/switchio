"""
Event loops!
"""
from .. import utils
from .reactor import EventLoop


def get_event_loop(host, port=EventLoop.PORT, auth=EventLoop.AUTH,
                   **kwargs):
    '''Event loop factory. When using python 3.5 + an ``asyncio`` based loop
    is used.
    '''
    if utils.py35:
        from .proactor import AsyncIOEventLoop
        return AsyncIOEventLoop(host, port, auth, **kwargs)
    else:
        return EventLoop(host, port, auth, **kwargs)
