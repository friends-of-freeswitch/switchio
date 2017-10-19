# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Connection wrappers
"""
from .. import utils


class ConnectionError(utils.ESLError):
    "Failed to connect to ESL"


def get_connection(host, port=8021, password='ClueCon', loop=None):
    """ESL connection factory.
    """
    if utils.py35:
        import asyncio
        from threading import get_ident
        from .aioesl import AsyncIOConnection
        loop = loop or asyncio.get_event_loop()
        loop._tid = get_ident()
        return AsyncIOConnection(host, port=port, password=password, loop=loop)
    else:
        from .swig import SWIGConnection
        return SWIGConnection(host, port=port, auth=password)
