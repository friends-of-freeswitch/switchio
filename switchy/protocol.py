# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2017 Tyler Goodlet <tgoodlet@gmail.com>
"""
Inbound ESL asyncio protocol
"""
import asyncio
from collections import defaultdict, deque
from six.moves.urllib.parse import unquote
from . import utils


class InboundProtocol(asyncio.Protocol):
    """Inbound ESL client which delivers parsed events to an
    ``asyncio.Queue``.
    """
    def __init__(self, password, loop, connection):
        self.password = password
        self.loop = loop
        self.event_queue = asyncio.Queue(loop=loop)
        self.con = connection
        self.host = connection.host
        self.log = utils.get_logger(utils.pstr(self))
        self.transport = None
        self._curr_event = {}

        # state flags
        self._connected = False
        self.disconnected = None
        self._auth_resp = None

        # futures to be set and waited on for the following content types
        self._futures_map = defaultdict(deque)
        for ctype in [
            'command/reply', 'auth/request', 'api/response',
            'text/disconnect-notice'
        ]:
            self._futures_map.get(ctype)

    def connected(self):
        return self._connected

    def connection_made(self, transport):
        """Login with ESL password on connection.
        """
        self.log.debug("Connection made to {}".format(self.host))
        self.transport = transport
        self.max_size = transport.max_size
        self._connected = True
        self.disconnected = self.loop.create_future()
        self.authenticate()

    def connection_lost(self, exc):
        self._connected = False
        self._auth_resp = None
        self.log.debug('The server closed @ {}'.format(self.host))
        self.disconnected.set_result(True)

    def reg_fut(self, ctype, fut=None):
        """Register and return a future wrapping an event packet to be
        received according to the Content-Type ``ctype``.
        """
        fut = fut or self.loop.create_future()
        self._futures_map[ctype].append(fut)
        return fut

    def authenticated(self):
        if self._auth_resp is None:
            return False
        return self._auth_resp.done() and not self._auth_resp.cancelled()

    def authenticate(self):
        if self._auth_resp is None:
            auth_req = self.reg_fut('auth/request')
            self._auth_resp = auth_resp = self.loop.create_future()

            def ack_auth(future):
                event = future.result()
                if event['Reply-Text'] != '+OK accepted':
                    self._auth_resp = None
                    raise ConnectionError("Invalid password?")

            def respond_to_auth(future):
                fut = self.sendrecv(
                    'auth {}'.format(self.password), fut=auth_resp)
                fut.add_done_callback(ack_auth)

            auth_req.add_done_callback(respond_to_auth)

        return self._auth_resp

    def process_event(self, event):
        """Process an event by activating futures or pushing to the queue.
        """
        # debugging - watch out pformat() is slow...
        # self.log.log(utils.TRACE, "Event packet:\n{}".format(pformat(event)))
        ctype = event.get('Content-Type', None)
        futures = self._futures_map.get(ctype, None)
        if futures is None:
            # standard inbound state update
            self.event_queue.put_nowait(event)
        else:
            try:
                fut = futures.popleft()
                fut.set_result(event)
            except IndexError:
                self.log.warn("No waiting future could be found "
                              "for event?\n{!r}".format(event))

    def data_received(self, data):
        """Main socket data processing routine. This is the core event packet
        parser and should be optimized for speed.
        """
        parsed = unquote(data.decode())
        self.log.log(utils.TRACE, 'Socket data received:\n{}'.format(parsed))
        lines = parsed.splitlines()
        events = deque(maxlen=1000)
        last_key = None
        value = ''
        event = self._curr_event
        chunk = {}  # lines between each '\n\n'
        keyed_chunk = False

        for line in lines:
            if line is '':  # end of chunk (delineated by '\n\n')
                event.update(chunk)
                chunk = {}
                keyed_chunk = False
                continue

            key, sep, value = line.partition(': ')

            if sep and key[0] is not '+':  # 'key: value' found

                # new event packet
                if key == 'Content-Length' or key == 'Content-Type':
                    # process the previous event packet
                    if event:
                        self.process_event(event)
                        events.append(event)
                        event = {}
                else:
                    last_key = key
                    keyed_chunk = True

                chunk[key] = value
            else:
                # no sep - 2 cases: multi-line value or body content
                key = last_key if keyed_chunk else 'Body'
                chunk[key] = chunk.setdefault(key, '') + line + '\n'

        if event:  # process any final packet in progress
            if chunk:  # trailing chunk?
                event.update(chunk)

            # The packet can be segmented over calls back
            # in which case we save the event and wait for
            # the next iteration.
            self._curr_event = event
            clen = event.get('Content-Length')
            if not clen or (clen and len(data) < self.max_size):
                # If the length of the transport data packet
                # is less then the max size it's likely this packet
                # is not segmented and can be processed now
                self.process_event(event)
                events.append(event)
                self._curr_event = {}

        return events  # for testing

    def send(self, data):
        """Write raw data to the transport.
        """
        msg = (data + '\n'*2).encode()
        self.log.log(utils.TRACE, 'Data sent: {!r}'.format(msg))
        self.transport.write(msg)

    def sendrecv(self, data, resp_type='command/reply', fut=None):
        """Send raw data to the transport and return a future representing
        a response.
        """
        if not self.connected():
            raise ConnectionError("Protocol is not connected")
        fut = self.reg_fut(resp_type, fut=fut)
        self.send(data)
        return fut

    @staticmethod
    def _handle_cmd_resp(future):
        event = future.result()
        body = event.get('Body', '')
        lines = body.splitlines()
        if lines and '-ERR' in lines[-1]:
            raise utils.APIError(body)

    def api(self, cmd, errcheck=True):
        future = self.sendrecv('api {}'.format(cmd), 'api/response')
        if errcheck:
            future.add_done_callback(self._handle_cmd_resp)

        return future

    def disconnect(self):
        """Disconnect this protocol.
        """
        def shutdown(future):
            event = future.result()
            reply = event['Reply-Text']
            if reply != '+OK bye':
                raise ConnectionError("Failed to disconnect with {}"
                                      .format(reply))

        exit_resp = self.sendrecv('exit')
        exit_resp.add_done_callback(shutdown)
        discon = self.reg_fut('text/disconnect-notice')
        return discon
