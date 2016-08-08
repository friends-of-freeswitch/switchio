# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
switchy: A FreeSWITCH control and stress testing micro framework.

Licensed under the MPL 2.0 license (see `LICENSE` file)
"""
import apps
from os import path
from utils import get_logger, ESLError
from observe import EventListener, Client, get_listener
from apps.call_gen import get_originator
from distribute import SlavePool, MultiEval
from marks import event_callback, handler
from connection import Connection, ConnectionError
from sync import sync_caller
from serve import Service


__package__ = 'switchy'
__version__ = '0.1.alpha'
__author__ = ('Sangoma Technologies', 'qa@eng.sangoma.com')


PARK_DP = path.join(path.dirname(__file__), '../conf', 'switchydp.xml')
