"""
Switchy
Licensed under the MPL license (see `LICENSE` file)

A fast FreeSWITCH ESL lib with a focus on load testing.

The EventListener component was inspired and reworked from Moises Silva's
'fs_test' project: https://github.com/moises-silva/fs_test

TODO:
    - Consider tearing down the last N calls when limit is descreased by N?
    - Move all fs looking logging into this package?
    - consider adding a 'register_observer/poller' interface where objects can
      ask to only receive events they care about from the listener?
      (listener might return an itr of callables for each consumer request?)
    - registration of clients for events associated with their id (i.e.
      events not pertaining to that id should trigger invocation of that
      client's callbacks)
    - connections collection so that any registered connections will be
      reconnected on server restart
    - register handlers/callbacks using decorator mechanism

useful event reg cmd:
/events plain CHANNEL_CREATE CHANNEL_ORIGINATE CHANNEL_HANGUP CHANNEL_ANSWER
SERVER_DISCONNECTED SOCKET_DATA BACKGROUND_JOB

useful debug:
uuid_dump <session-id>
"""
from os import path
from utils import get_logger, ESLError
from observe import EventListener, Client, get_listener
from apps.call_gen import get_originator
from distribute import SlavePool, MultiEval
from marks import event_callback, handler
from connection import Connection, ConnectionError

__package__ = 'switchy'
__version__ = '0.1.alpha'
__author__ = 'Tyler Goodlet (tgoodlet@sangoma.com, tgoodlet@gmail.com)'


PARK_DP = path.join(path.dirname(__file__), 'conf', 'switchydp.xml')
