# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
switchio: ``asyncio`` powered FreeSWITCH cluster control

Licensed under the MPL 2.0 license (see `LICENSE` file)
"""
from os import path
from .utils import get_logger, ESLError
from .api import get_client, Client
from .loop import get_event_loop
from .handlers import get_listener
from .apps.call_gen import get_originator
from .distribute import SlavePool, MultiEval
from .marks import event_callback, callback, handler, coroutine
from .connection import get_connection, ConnectionError
from .sync import sync_caller
from .serve import Service

__package__ = 'switchio'
__version__ = '0.1.0.alpha1'
__author__ = ('Sangoma Technologies', 'qa@eng.sangoma.com')
__all__ = [
    'get_logger',
    'ESLError',
    'get_client',
    'get_event_loop',
    'get_listener',
    'get_originator',
    'SlavePool',
    'MultiEval',
    'callback',
    'handler',
    'coroutine',
    'get_connection',
    'ConnectionError',
    'sync_caller',
    'Service',
]

PARK_DP = path.join(
    path.dirname(__file__),
    '../conf/ci-minimal/dialplan', 'switchiodp.xml'
)
