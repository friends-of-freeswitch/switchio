# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2017 Tyler Goodlet <tgoodlet@gmail.com>
"""
Inbound ESL asyncio protocol
"""
import asyncio
from collections import defaultdict, deque, namedtuple
from six.moves.urllib.parse import unquote
from . import utils

# debugging - watch out pformat() is slow...
# from pprint import pformat


class InboundProtocol(asyncio.Protocol):
    """Inbound ESL client which delivers parsed events to an
    ``asyncio.Queue``.
    """
    def __init__(self, password, loop, host):
        self.password = password
        self.loop = loop
        self.event_queue = asyncio.Queue(loop=loop)
        self.host = host
        self.log = utils.get_logger(utils.pstr(self))
        self.transport = None
        self._previous = None, None
        self._segmented = namedtuple('segmentdata', ['event', 'size'])({}, 0)

        # state flags
        self._connected = False
        self._disconnected = None
        self._auth_resp = None

        # futures to be set and waited on for the following content types
        self._futures_map = defaultdict(deque)
        for ctype in ['command/reply', 'auth/request', 'api/response']:
            self._futures_map.get(ctype)

    def connected(self):
        return self._connected

    def disconnected(self):
        """Return a future that can be used to wait for the connection
        to tear down.
        """
        return self._disconnected if self._disconnected else False

    def connection_made(self, transport):
        """Login with ESL password on connection.
        """
        self.log.debug("Connection made to {}".format(self.host))
        self.transport = transport
        self._connected = True
        self._disconnected = self.loop.create_future()
        self.authenticate()

    def connection_lost(self, exc):
        self._connected = False
        self._auth_resp = None
        self.log.debug('The connection closed @ {}'.format(self.host))
        self._disconnected.set_result(True)

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

    def process_events(self, events, parsed):
        """Process an event by activating futures or pushing to the queue.
        """
        fut_map = self._futures_map
        for event in events:
            # self.log.log(
            #     utils.TRACE, "Event packet:\n{}".format(pformat(event)))
            ctype = event.get('Content-Type', None)
            futures = fut_map.get(ctype, None)

            if ctype == 'text/disconnect-notice':
                event['Event-Name'] = 'SERVER_DISCONNECTED'
                self.event_queue.put_nowait(event)
                return

            if futures is None:  # ship it for consumption
                self.event_queue.put_nowait(event)
            else:
                try:
                    fut = futures.popleft()
                    fut.set_result(event)
                except IndexError:
                    self.log.warn("No waiting future could be found "
                                  "for event?\n{!r}".format(event))

    @staticmethod
    def parse_frame(frame):
        parsed = unquote(frame)
        chunk = {}
        last_key = 'Body'
        for line in parsed.strip().splitlines():
            if not line:
                last_key = 'Body'
                continue
            key, sep, value = line.partition(': ')
            if sep and key and key[0] is not '+':  # 'key: value' header
                last_key = key
                chunk[key] = value
            else:
                # no sep - 2 cases: multi-line value or body content
                chunk[last_key] = chunk.setdefault(
                    last_key, '') + line + '\n'
        return chunk

    def read_contents(self, data, iframe, clen):
        chunk = {}
        segmented = False
        # while clen:  # recursive clens?
        clen = int(clen)
        contents = data[iframe:iframe+clen]
        if contents:
            chunk.update(self.parse_frame(contents))
        diff = clen - len(contents)
        # if len(contents) != clen:
        if diff > 0:
            segmented = True
            # break
        iframe = iframe + clen
        # clen = chunk.get('Content-Length')
        return chunk, segmented, diff, iframe

    def data_received(self, data):
        """Main socket data processing routine. This is the core event packet
        parser and should be optimized for speed.
        """
        data = data.decode()
        parsed = unquote(data)
        self.log.log(utils.TRACE, 'Socket data received:\n{}'.format(parsed))
        events = deque(maxlen=1000)

        # get any segmented event in progress
        event, content_size = self._segmented
        self._segmented = {}, 0
        segmented = False

        iframe = 0
        # finish processing segments
        if content_size:
            chunk, segmented, diff, iframe = self.read_contents(
                data, 0, content_size)
            event.update(chunk)
            if segmented:
                self._segmented = event, diff
                return []

        s = data.find('\n\n')
        while s != -1:
            frame = data[iframe:s+1]
            chunk = self.parse_frame(frame)
            event.update(chunk)

            iframe = s+2
            clen = chunk.get('Content-Length')
            if clen:
                chunk, segmented, diff, iframe = self.read_contents(
                    data, iframe, clen)
                if chunk:
                    event.update(chunk)
                if segmented:
                    self._segmented = event, diff
                    break

            events.append(event)
            event = {}
            s = data.find('\n\n', iframe)

        self.process_events(events, parsed)
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

    def _handle_cmd_resp(self, future):
        event = future.result()
        resp = event.get('Body', event.get('Reply-Text', ''))
        if not resp:
            raise RuntimeError("Missing a response?")
        lines = resp.splitlines()
        if lines and '-ERR' in lines[-1]:
            self.log.error("Event {} reported\n{}".format(event, resp))
        return event

    def bgapi(self, cmd, errcheck=True):
        future = self.sendrecv('bgapi {}'.format(cmd))
        if errcheck:
            future.add_done_callback(self._handle_cmd_resp)

        return future

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
        return self._disconnected
