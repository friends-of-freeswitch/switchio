# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2017 Tyler Goodlet <tgoodlet@gmail.com>
"""
Asyncio ESL connection abstactions
"""
import asyncio
from functools import partial
from concurrent import futures
from threading import get_ident
from . import utils
from .protocol import InboundProtocol


class ConnectionError(utils.ESLError):
    "Failed to connect to ESL"


async def await_in_order(awaitables, loop, timeout=None):
    awaitables = map(partial(asyncio.ensure_future, loop=loop), awaitables)
    for awaitable in awaitables:
        try:
            res = await asyncio.wait_for(awaitable, timeout=timeout, loop=loop)
        except (asyncio.CancelledError, asyncio.TimeoutError) as err:
            for awaitable in awaitables:
                awaitable.cancel()
            raise

    return res


def run_in_order_threadsafe(awaitables, loop, timeout=0.5, block=True):
    """"Given a sequence of awaitables, schedule each threadsafe in order
    optionally blocking until completion.

    Returns a `concurrent.futures.Future` which can be used to wait on the
    result returned from the last awaitable. If `block` is `True` the final
    result will be waited on before returning control to the caller.
    """
    future = asyncio.run_coroutine_threadsafe(
        await_in_order(awaitables, loop, timeout),
        loop
    )

    if block:
        if not loop.is_running():
            result = loop.run_until_complete(
                asyncio.wrap_future(future, loop=loop))
            assert result is future.result()
        else:
            future.result(timeout)

    return future


async def connect_and_auth(host, port, password, prot, loop, log, timeout=0.5):
    """Try to create a connection and authenticate to the
    target FS ESL.
    """
    msg = ("Failed to connect to server at '{}:{}'\n"
           "Please check that FreeSWITCH is running and "
           "accepting ESL connections.".format(host, port))
    try:
        await asyncio.wait_for(
            loop.create_connection(lambda: prot, host, port),
            timeout=timeout)
    except (
        ConnectionRefusedError, asyncio.TimeoutError, OSError,
        futures.TimeoutError,
    ) as err:
        raise ConnectionError(msg.format(host, port))

    # TODO: consider using the asyncio_timeout lib here
    try:
        await asyncio.wait_for(prot.authenticate(), timeout)
    except asyncio.TimeoutError:
        raise ConnectionRefusedError(msg.format(host, port))


async def async_reconnect(host, port, password, prot, loop, log):
    log.info("Attempting to reconnect to {}:{}".format(host, port))
    log.info(f'async_reconnect: {prot.autorecon}')
    if not prot.autorecon:
        log.debug("Autorecon had been disabled")
        return
    elif prot.autorecon is True:
        while True:
            try:
                await connect_and_auth(
                    host, port, password, prot, loop, log, timeout=1)
                break
            except ConnectionError:
                log.warning(
                    f"Failed reconnection attempt... will retry in "
                     "{prot.reconnect_delay} seconds...")
                await asyncio.sleep(prot.reconnect_delay)
    else:
        count = prot.autorecon
        for i in range(count):
            try:
                await connect_and_auth(
                    host, port, password, prot, loop, log, timeout=1)
                break
            except ConnectionError:
                log.warning(
                    "Failed reconnection attempt...retries"
                    " left {}".format(count - i))
                await asyncio.sleep(prot.reconnect_delay)
        else:
            log.warning(
                "Reconnection attempts to '{}' failed. Please call"
                " 'connect' manually when server is ready "
                .format(host))

    if prot.connected():
        log.info("Successfully reconnected to '{}:{}'"
                 .format(host, port))


class Connection(object):
    """An ESL connection implemented using an ``asyncio`` TCP protocol.

    Consider this API threadsafe.

    :param autorecon:
        Enable reconnection attempts on loss of a server connection.
        An integer value specifies the of number seconds to spend
        re-trying the connection before bailing. A bool of 'True'
        will poll indefinitely and 'False' will not poll at all.
    :type autorecon: int or bool
    """
    def __init__(self, host, port='8021', password='ClueCon', loop=None,
                 autorecon=30, reconnect_delay=0.1):
        """
        Parameters
        -----------
        host : string
            host name or ip address for server hosting an esl connection.
        port : string
            port where esl connection socket is being offered.
        password : string
            authentication password for esl connection.
        """
        self.host = host
        self.port = port
        self.password = password
        self.log = utils.get_logger(utils.pstr(self))
        self._sub = ()  # events subscription
        self.loop = loop
        self.autorecon = autorecon
        self.reconnect_delay = reconnect_delay
        self.protocol = None
        self.log.debug(f'Connection.__init__: {self.autorecon}')

    def __enter__(self, **kwargs):
        self.connect(**kwargs)
        return self

    def __exit__(self, exception_type, exception_val, trace):
        self.disconnect()

    def connect(
            self, host=None, port=None, password=None, loop=None,
            block=True,
            timeout=0.5  # seems to be the optimal wait value
    ):
        """Connect the underlying protocol.

        If ``block`` is set to false returns a coroutine.
        """
        host = host or self.host
        port = port or self.port
        password = password or self.password
        self.loop = loop if loop else self.loop
        loop = self.loop

        self.log.debug(f'Connection.connect: {self.autorecon}')

        if not self.connected() or not block:

            def reconnect(prot):
                """Schedule a reconnection task.
                """
                self.log.debug("Scheduling a reconnection task")
                asyncio.ensure_future(async_reconnect(
                    host, port, password, prot,
                    loop, self.log), loop=loop)

            self.log.debug(f'Connection.connect:protocol: {self.autorecon}')
            prot = self.protocol = InboundProtocol(
                self.host, password, loop, autorecon=self.autorecon,
                on_disconnect=reconnect, reconnect_delay=self.reconnect_delay)

            coro = connect_and_auth(
                host, port, password, prot, self.loop, self.log)

            if block:  # wait for authorization sequence to complete
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(coro, loop=loop).result(3)
                else:
                    loop.run_until_complete(coro)

                if not prot.connected() and not prot.authenticated():
                    raise ConnectionError(
                        "Failed to connect to server at '{}:{}'\n"
                        "Please check that FreeSWITCH is running and "
                        "accepting ESL connections.".format(host, port))
            else:
                return coro

    def connected(self):
        return self.protocol.connected() if self.protocol else False

    def disconnect(self, block=True, loop=None):
        loop = loop or self.loop
        if self.connected():
            if not block and (get_ident() == loop._tid):
                return self.protocol.disconnect()

            return run_in_order_threadsafe(
                [self.protocol.disconnect(),
                 self.protocol.disconnected()],
                loop, timeout=2, block=block
            ).result()

    async def recv_event(self):
        """Retreive the latest queued event.
        """
        queue = self.protocol.event_queue
        event = await queue.get()
        queue.task_done()
        return event

    def execute(self, uuid, app, arg='', params='', loops=1):
        """Execute a dialplan ``app`` with argument ``arg``.
        """
        return self.protocol.sendmsg(uuid, 'execute', app, arg, params,
                                     loops=loops)

    def api(self, cmd, errcheck=True, block=False, timeout=0.5):
        '''Invoke api command (with error checking by default).
        '''
        if not self.connected():
            raise ConnectionError("Call ``connect()`` first")
        self.log.debug("api cmd '{}'".format(cmd))
        if not block and (get_ident() == self.loop._tid):
            # note this is an `asyncio.Future`
            return self.protocol.api(cmd, errcheck=errcheck)

        # NOTE: this is a `concurrent.futures.Future`
        future = run_in_order_threadsafe(
            [self.protocol.api(cmd, errcheck=errcheck)],
            self.loop,
            timeout=timeout,
            block=block,
        )

        if not block:
            return future

        return future.result(0.005)

    def cmd(self, cmd):
        '''Return the string-body output from invoking a command.
        '''
        event = self.api(cmd, block=True)
        _, body = self._handle_socket_data(event)
        return body

    def bgapi(self, cmd, block=False):
        self.log.debug("bgapi cmd '{}'".format(cmd))
        if not block and (get_ident() == self.loop._tid):
            return self.protocol.bgapi(cmd)  # note this is an `asyncio.Future`

        future = run_in_order_threadsafe(
            [self.protocol.bgapi(cmd)],
            self.loop,
            block=block
        )

        if not block:
            return future  # note this is a `concurrent.futures.Future`

        return future.result(0.005)

    def subscribe(self, event_types, fmt='plain'):
        """Subscribe connection to receive events for all names
        in `event_types`
        """
        std = []
        custom = []
        for name in event_types:
            if '::' in name:
                custom.append(name)
            else:
                std.append(name)
            self._sub += (name,)

        if custom:
            std = ['CUSTOM'] + custom

        fut = self.protocol.sendrecv(
            "event {} {}".format(fmt, ' '.join(std))
        )
        return fut

    def new_connection(self):
        return type(self)(
            self.host, self.port, self.password, loop=self.loop)

    @staticmethod
    def _handle_socket_data(event):
        body = event.get('Body') if event else None
        if not body:
            return False, None
        if '-ERR' in body.splitlines()[-1]:
            raise utils.APIError(body)
        return True, body


def get_connection(host, port=8021, password='ClueCon', loop=None,
                   autorecon=30, reconnect_delay=0.1):
    """ESL connection factory.
    """
    loop = loop or asyncio.get_event_loop()
    loop._tid = get_ident()
    return Connection(host, port=port, password=password,
                      loop=loop, autorecon=autorecon, reconnect_delay=reconnect_delay)
