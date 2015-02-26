# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab
#
# Copyright (C) 2013  Sangoma Technologies Corp.
# All Rights Reserved.
# Author(s)
# Tyler Goodlet <tgoodlet@sangoma.com>
import pytest
import time


def pytest_addoption(parser):
    '''Add server options for pointing to the engine we will use for testing
    '''
    parser.addoption("--fshost", action="store", dest='fshost',
                     default=None,
                     help="fs-engine server host or ip")
    parser.addoption("--fsport", action="store", dest='fsport',
                     default=5080,
                     help="fs-engine contact port")
    parser.addoption("--cps", action="store", dest='cps',
                     default=200,
                     help="num of sipp calls to launch per second")


@pytest.fixture(scope='module')
def fshost(request):
    '''return the fshost option string
    '''
    fshost = request.config.option.fshost
    if fshost:
        return fshost
    pytest.skip("the '--fshost' option is required to determine the fs"
                " slave server")


@pytest.fixture(scope='module')
def fssock(request, fshost):
    '''return the fshost,fsport values as tuple (str, int)
    Use port 5080 (fs external profile) by default
    '''
    return fshost, request.config.option.fsport


@pytest.fixture
def cps(request):
    """It appears as though fs can deliver channel create events at
    around 250 cps (don't know if we can even track faster
    then this) IF the calls are bridged directly using an xml
    dialplan (can get close with a pure esl dp and a fast server).
    Bridging them using the proxy_dp fixture above we can only
    get around 165 for slow servers...
    """
    cps = int(request.config.option.cps)
    return cps if cps < 250 else 250


@pytest.yield_fixture
def con(fshost):
    '''Deliver a esl connection to fshost
    '''
    from ..connection import Connection
    with Connection(fshost) as con:
        yield con


@pytest.yield_fixture
def el(fshost):
    'deliver a connected event listener'
    from sangoma.switchy import get_listener
    el = get_listener(fshost)
    assert not el.connected()
    yield el
    el.disconnect()
    # verify state
    assert not el.connected()
    assert not el.is_alive()


@pytest.yield_fixture(scope='class')
def client(fshost):
    """Deliver a core.Client connected to fshost
    """
    from .. import Client
    cl = Client(fshost)
    yield cl
    cl.disconnect()
    assert not cl.connected()
