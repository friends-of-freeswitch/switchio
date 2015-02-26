"""
ESL connection wrapper
"""
import time
from ESL import ESLconnection
import functools
from utils import ESLError
import utils
import multiprocessing as mp


class ConnectionError(ESLError):
    pass


def check_con(con):
    '''Raise a connection error if this connection is down
    '''
    # XXX sometimes after the 1st cmd sent to the server
    # the connection will be lost? (lib esl bug?)
    if not con:
        return False
    event = con.api('status')
    return bool(con.connected()) and bool(event)


class Connection(object):
    '''
    Connection wrapper which can provide mutex attr access making the
    underlying ESL.ESLconnection thread safe

    Note
    ----
    This class must be explicitly connected before use.
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

    def api(self, cmd):
        self.log.debug("api cmd '{}'".format(cmd))
        with self._mutex:
            try:
                return self._con.api(cmd)
            except AttributeError:
                raise ConnectionError("call `connect` first")

    def bgapi(self, cmd):
        self.log.debug("bgapi cmd '{}'".format(cmd))
        with self._mutex:
            try:
                return self._con.bgapi(cmd)
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

    def connect(self, **kwargs):
        """Reconnect if disconnected
        """
        host = kwargs.pop('host', None) or self.host
        port = kwargs.pop('port', None) or self.port
        auth = kwargs.pop('auth', None) or self.auth
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
