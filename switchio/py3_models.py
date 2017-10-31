"""
Custom models until we're py3.5+ only.
"""
import asyncio
from . models import Session



class Session(Session):
    """Extend with ``asyncio`` compatible API.
    """
    def unreg_tasks(self, fut):
        self.tasks.pop(fut)
        if fut.cancelled():  # otherwise it's popped in the event loop
            self._futures.pop(fut._evname)

    def recv(self, name, timeout=None):
        """Return an awaitable which resumes once the event-type ``name``
        is received for this session.
        """
        loop = self.event_loop.loop
        fut = self._futures.setdefault(name, loop.create_future())
        fut._evname = name
        caller = asyncio.Task.current_task(loop)
        # keep track of consuming coroutines
        self.tasks.setdefault(fut, []).append(caller)
        fut.add_done_callback(self.unreg_tasks)
        return fut if not timeout else asyncio.wait_for(
            fut, timeout, loop=loop)

    async def poll(self, events, timeout=None,
                   return_when=asyncio.FIRST_COMPLETED):
        """Poll for any of a set of event types to be received for this session.
        """
        awaitables = {}
        for name in events:
            awaitables[self.recv(name)] = name
        done, pending = await asyncio.wait(
            awaitables, timeout=timeout, return_when=return_when)

        if done:
            ev_dicts = []
            for fut in done:
                awaitables.pop(fut)
                ev_dicts.append(fut.result())
            return ev_dicts, awaitables.values()
        else:
            raise asyncio.TimeoutError(
                "None of {} was received in {} seconds"
                .format(events, timeout))
