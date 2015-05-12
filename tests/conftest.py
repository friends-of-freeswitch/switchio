# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest
import sys


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


def pytest_configure(config):
    if sys.stdout.isatty():
        # enable console logging
        from switchy import utils
        utils.log_to_stderr(max(40 - config.option.verbose * 10, 10))


@pytest.fixture(scope='session')
def fshosts(request):
    argstring = request.config.option.fshost
    if not argstring:
        pytest.skip("the '--fshost' option is required to determine the "
                    "FreeSWITCH slave server(s) under test")
    # construct a list if passed as arg
    if '[' in argstring:
        fshosts = eval(argstring)
        assert iter(fshosts), '`--fshost` list is not a valid python sequence?'
    else:
        fshosts = [argstring]

    return fshosts


@pytest.fixture(scope='session')
def fshost(fshosts):
    '''return the first fs slave hostname passed via the
    `--fshost` cmd line arg
    '''
    return fshosts[0]


@pytest.fixture(scope='module')
def fsip(fshost):
    '''Convert provided host name to ip addr via dns
    (Useful for loop back call tests)
    '''
    import socket
    return socket.gethostbyname(socket.getfqdn(fshost))


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
    from switchy.connection import Connection
    with Connection(fshost) as con:
        yield con


@pytest.yield_fixture
def el(fshost):
    'deliver a connected event listener'
    from switchy import get_listener
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
    from switchy import Client
    cl = Client(fshost)
    yield cl
    cl.disconnect()
    assert not cl.connected()
