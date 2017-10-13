# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
SWIG ESL connection wrappers
"""
import time
import functools
import multiprocessing as mp
from ESL import ESLconnection  # requires python-ESL and swig
from . import ConnectionError
from .. import utils


def check_con(con):
    '''Raise a connection error if this connection is down.
    '''
    # XXX sometimes after the 1st cmd sent to the server
    # the connection will be lost? (lib esl bug?)
    if not con:
        return False
    event = con.api('status')
    return bool(con.connected()) and bool(event)


class SWIGConnection(object):
    '''Connection wrapper which can provide mutex attr access making the
    underlying ESL.ESLconnection thread safe.

    (Note: must be explicitly connected before use.)
    '''
    def __init__(self, host, port='8021', auth='ClueCon',
                 locked=True, lock=None):
        """
        Parameters
        -----------
        host : string
            host name or ip address for server hosting an esl connection.
        port : string
            port where esl connection socket is being offered.
        auth : string
            authentication password for esl connection.
        locked : bool
            indicates whether to return a thread safe derivative of the default
            ESLConnection class.
        lock : instance of mp.Lock
            a lock implementation which the connection will utilize when
            serializing accesses from multiple threads (requires locked=True)
        """
        self.host = host
        self.port = port
        self.auth = auth
        self.log = utils.get_logger(utils.pstr(self))
        self._sub = ()  # events subscription
        if locked:
            self._mutex = lock or mp.Lock()
        # don't connect by default
        self._con = False

    def __enter__(self, **kwargs):
        self.connect(**kwargs)
        return self

    def __exit__(self, exception_type, exception_val, trace):
        self.disconnect()

    @staticmethod
    def _handle_socket_data(event):
        body = event.getBody() if event else None
        if not body:
            return False, None
        if '-ERR' in body.splitlines()[-1]:
            raise utils.APIError(body)
        return True, body

    def _preproc_event(self, e):
        """Pre-process an event for API compatibility.
        """
        e.get = e.getHeader  # mapping compat
        return e

    def api(self, cmd, errcheck=True, timeout=None):
        '''Invoke esl api command (with error checking by default).
        Returns an ESL.ESLEvent instance for event type "SOCKET_DATA".
        '''
        self.log.debug("api cmd '{}'".format(cmd))
        with self._mutex:
            try:
                event = self._preproc_event(self._con.api(cmd))
                if errcheck:
                    _, body = self._handle_socket_data(event)
                return event
            except AttributeError:
                raise ConnectionError("call `connect` first")

    def cmd(self, cmd):
        '''Return the string-body output from invoking a command.
        '''
        return self.api(cmd).getBody().strip()

    def bgapi(self, cmd):
        self.log.debug("bgapi cmd '{}'".format(cmd))
        with self._mutex:
            try:
                return self._preproc_event(self._con.bgapi(cmd))
            except AttributeError:
                raise ConnectionError("call `connect` first")

    def __getattr__(self, name):
        if name == '_con':
            return object.__getattribute__(self, name)
        try:
            attr = getattr(self._con, name)
            if not callable(attr):
                return attr
            else:
                # wrap callables with a mutex
                @functools.wraps(attr)
                def method(*args, **kwargs):
                    with self._mutex:
                        return attr(*args, **kwargs)
                return method
        except AttributeError:
            if name in dir(ESLconnection):
                raise AttributeError(
                    "Call `connect()` before before accessing the '{}' "
                    "attribute".format(name))
            else:
                raise

    def __dir__(self):
        dircon = dir(self._con) if self.connected() else []
        return utils.dirinfo(self) + dircon

    def disconnect(self):
        """Rewrap disconnect to avoid deadlocks
        """
        if self.connected():
            ret = self._con.disconnect()
            self._sub = ()  # reset subscription
            return not bool(ret)
        return False

    def connect(self, host=None, port=None, auth=None):
        """Reconnect if disconnected
        """
        host = host or self.host
        port = port or self.port
        auth = auth or self.auth
        if not self.connected():
            # XXX: try a few times since connections seem to be flaky
            # We should probably try to fix this in the _ESL.so
            for _ in range(5):
                self._con = ESLconnection(*map(str, (host, port, auth)))
                time.sleep(0.05)  # I wouldn't tweak this if I were you.
                if self.connected() and check_con(self._con):
                        break
                else:
                    self._con = False
        if not check_con(self._con):
            raise ConnectionError(
                "Failed to connect to server at '{}:{}'\n"
                "Please check that FreeSWITCH is running and "
                "accepting esl connections.".format(host, port))

    def connected(self):
        '''Return bool indicating if this connection is active
        '''
        if not self._con:
            return False
        return bool(self._con.connected())

    def subscribe(self, event_types, fmt='plain'):
        """Subscribe connection to receive events for all names
        in `event_types`
        """
        if not self.connected():
            raise ConnectionError(
                "connection must be active before registering for events")
        for name in event_types:
            prefix = 'CUSTOM ' if "::" in name else ''
            self._con.events(fmt, "{}{}".format(prefix, name))
            self._sub += (name,)

    def new_connection(self):
        return type(self)(self.host, self.port, self.auth)

    def recv_event(self):
        return self._preproc_event(self._con.recvEvent())

    def fileno(self):
        """Returns the file descriptor (number).
        Provide API compat with file-like objects.
        """
        return self._con.socketDescriptor()
