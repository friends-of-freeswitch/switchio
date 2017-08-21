# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2017 Tyler Goodlet <tgoodlet@gmail.com>
"""
Asyncio ESL connection abstactions
"""
import asyncio
import time
from functools import partial
from threading import get_ident
from . import ConnectionError
from .. import utils
from ..protocol import InboundProtocol


def run_in_loop(futs, loop, timeout=0.5, block=True, call=False):
    """"Given a sequence of futures ``futs``, handle each in order to
    completion and return the final result.
    """
    async def runall(futs):
        ffuts = []
        for fut in futs:
            if call:
                fut = fut()
            ffuts.append(fut)
            asyncio.ensure_future(fut, loop=loop)
            await asyncio.wait_for(fut, timeout=timeout if block else None)
        return ffuts[-1].result()

    coro = runall(futs)

    if not loop.is_running() and block:
        return loop.run_until_complete(coro)
    else:
        future = asyncio.run_coroutine_threadsafe(coro, loop)

    if not block:
        return future

    return future.result(timeout)


class AsyncIOConnection(object):
    """An ESL connection implemented using an asyncio TCP protocol.
    Consider this API threadsafe.
    """
    def __init__(self, host, port='8021', password='ClueCon', loop=None):
        """
        Parameters
        -----------
        host : string
            host name or ip address for server hosting an esl connection.
        port : string
            port where esl connection socket is being offered.
        auth : string
            authentication password for esl connection.
        """
        self.host = host
        self.port = port
        self.password = password
        self.log = utils.get_logger(utils.pstr(self))
        self._sub = ()  # events subscription
        self.loop = loop
        self.protocol = None

    def __enter__(self, **kwargs):
        self.connect(**kwargs)
        return self

    def __exit__(self, exception_type, exception_val, trace):
        self.disconnect()

    async def aconnect(self, host, port, password, loop):
        """Async connect to the target FS ESL. ``connect()`` calls this method
        internally.
        """
        prot = self.protocol

        for _ in range(5):
            try:
                await loop.create_connection(lambda: prot, host, port)
                break
            except ConnectionRefusedError:
                time.sleep(0.05)  # I wouldn't tweak this if I were you.
                self.log.warning(
                    "Connection to {}:{} failed, retrying..."
                    .format(host, port)
                )
        else:
            raise ConnectionRefusedError(
                "Failed to connect to server at '{}:{}'\n"
                "Please check that FreeSWITCH is running and "
                "accepting ESL connections.".format(host, port))

        await asyncio.wait_for(prot.authenticate(), 10)

    def connect(self, host=None, port=None, password=None, loop=None,
                block=True):
        """Connect the underlying protocol.
        If ``block`` is set to false returns a coroutine.
        """
        host = host or self.host
        port = port or self.port
        password = password or self.password
        self.loop = loop if loop else self.loop
        loop = self.loop

        if not self.connected():
            self.protocol = InboundProtocol(password, loop, self.host)
            prot = self.protocol
            coro = self.aconnect(host, port, password, self.loop)

            if block:  # wait for authorization sequence to complete
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

    async def adisconnect(self, timeout=3):
        if self.connected():
            await asyncio.wait_for(self.protocol.disconnect(), timeout)

    def disconnect(self, block=True, loop=None):
        if self.connected():
            fut = self.protocol.disconnect()
            if not block and (get_ident() == self.loop._tid):
                return fut

            loop = loop or self.loop
            run_in_loop([fut, self.protocol.disconnected()],
                        loop, timeout=2)

    async def recv_event(self):
        """Retreive the latest queued event.
        """
        queue = self.protocol.event_queue
        event = await queue.get()
        queue.task_done()
        return event

    def api(self, cmd, errcheck=True, block=False):
        '''Invoke esl api command (with error checking by default).
        '''
        if not self.connected():
            raise ConnectionError("Call ``connect()`` first")
        self.log.debug("api cmd '{}'".format(cmd))
        if not block and (get_ident() == self.loop._tid):
            return self.protocol.api(cmd, errcheck=errcheck)

        return run_in_loop([partial(self.protocol.api, cmd,
                                    errcheck=errcheck)],
                           self.loop, block=block, call=True)

    def cmd(self, cmd):
        '''Return the string-body output from invoking a command.
        '''
        event = self.api(cmd, block=True)
        _, body = self._handle_socket_data(event)
        return body

    def bgapi(self, cmd, block=False):
        self.log.debug("bgapi cmd '{}'".format(cmd))
        fut = self.protocol.bgapi(cmd)
        return run_in_loop([fut], self.loop, timeout=0.005, block=block)

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
