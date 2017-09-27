# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2017 Tyler Goodlet <tgoodlet@gmail.com>
"""
Asyncio based reactor core
"""
import asyncio
from functools import partial
from collections import deque
import time
from threading import Thread, current_thread, get_ident
from .async import EventLoop
from . import utils


def new_event_loop():
    """Get the fastest loop available.
    """
    try:
        import uvloop
        return uvloop.new_event_loop()
    except ImportError as err:
        utils.log_to_stderr().warn(str(err))
        return asyncio.new_event_loop()


class AsyncIOEventLoop(EventLoop):
    """Re-implementation of the event loop with ``asyncio`` and coroutines
    support.
    """
    def _run_loop(self):
        self.loop = loop = new_event_loop()
        loop._tid = get_ident()
        loop.set_debug(True)
        asyncio.set_event_loop(loop)
        self.loop.run_forever()

    def _launch_bg_loop(self):
        if self._thread is None or not self._thread.is_alive():
            self.log.debug("starting event loop thread...")
            self._thread = Thread(
                target=self._run_loop, args=(),
                name='switchy_event_loop[{}]'.format(self.host),
            )
            self._thread.daemon = True  # die with parent
            self._thread.start()

    def connect(self, loop=None):
        '''Initialize underlying receive connection.
        '''
        # TODO: once we remove SWIG/py27 support this check can be removed
        if self.connected() and self.is_alive():
            raise utils.ConfigurationError(
                "event loop is already active, call 'disconnect()' first")
        elif self.connected():
                self.log.info("event loop is already connected")
                return

        if not self.is_alive():
            self._launch_bg_loop()
            while not self.loop:
                time.sleep(0.1)

        future = asyncio.run_coroutine_threadsafe(
            self._rx_con.connect(block=False, loop=self.loop), self.loop)
        future.result(1)

        # subscribe for events
        self._rx_con.subscribe(
            (ev for ev in self._handlers if ev not in self._unsub))
        self.log.info("Connected event loop '{}' to '{}'".format(self._id,
                      self.host))

    def start(self):
        '''Start this loop's listen coroutine and start processing
        all received events.
        '''
        if not self._rx_con.connected():
            raise utils.ConfigurationError("you must call 'connect' first")

        self.listen = asyncio.run_coroutine_threadsafe(
            self._listen_forever(), loop=self.loop)

    async def _listen_forever(self):
        '''Process events until stopped
        '''
        self.log.debug("starting listen loop")
        self._running = True
        while self._rx_con.connected():
            # block waiting for next event
            e = await self._rx_con.recv_event()
            # self.log.warning(get_event_time(e) - self._fs_time)
            if e is None:
                self.log.debug("Exiting listen loop")
                break
            elif not e:
                self.log.error("Received empty event!?")
            else:
                evname = e.get('Event-Name')
                if evname:
                    consumed = self._process_event(e, evname)
                    if not consumed:
                        self.log.warn("unconsumed  event '{}'?".format(e))
                else:
                    self.log.warn("received unnamed event '{}'?".format(e))

        self.log.debug("Exiting listen loop")
        self._running = False

    def _stop(self):
        '''Stop bg thread and event loop.
        '''
        if current_thread() is self._thread:
            self.log.warn("Stop called from event loop thread?")

        future = asyncio.run_coroutine_threadsafe(
            self._rx_con.adisconnect(), self.loop
        )
        # wait on disconnect success
        future.result(1)
        while self._rx_con.connected():
            time.sleep(0.1)

        def trigger_exit():
            # manually signal listen-loop exit (usually stuck in polling
            # the queue for some weird reason?)
            self.loop.call_soon_threadsafe(
                self._rx_con.protocol.event_queue.put_nowait, None)

        # trigger event consumer to terminate
        trigger_exit()
        pending = asyncio.Task.all_tasks(self.loop)
        self.loop.call_soon_threadsafe(
            partial(asyncio.gather, *pending, loop=self.loop))

        # tear down the event loop
        self.loop.stop()
        for _ in range(10):
            if self.loop.is_running():
                trigger_exit()
                time.sleep(0.1)
            else:
                break
        else:
            if self.loop.is_running():
                raise TimeoutError("Failed to stop event loop {}"
                                   .format(self.loop))

    def add_handler(self, evname, handler):
        """Register an event handler for events of type ``evname``.
        If a handler for ``evname`` already exists or if ``evname`` is in the
        unsubscribe list an error will be raised.
        """
        if evname in self._unsub:
            raise utils.ConfigurationError(
                "'{}' events have been unsubscribed for this event loop"
                .format(evname))
        # TODO: add a force option which allows overwrite?
        if evname in self._handlers:
            raise utils.ConfigurationError(
                "handler '{}' for events of type '{}' already exists"
                .format(self._handlers[evname], evname))

        if self._rx_con.connected() and evname not in self._rx_con._sub:
            self._rx_con.subscribe((evname,))
        # add handler to active map
        self._handlers[evname] = handler
