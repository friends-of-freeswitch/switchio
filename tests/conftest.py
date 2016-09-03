# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest
import socket
import sys
import itertools
import tempfile
from distutils import spawn
from switchy.utils import ncompose


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


@pytest.fixture(scope='session', autouse=True)
def loglevel(request):
    level = max(40 - request.config.option.verbose * 10, 10)
    if sys.stdout.isatty():
        # enable console logging
        from switchy import utils
        utils.log_to_stderr(level)

    return level


@pytest.fixture(scope='session')
def fshosts(request):
    '''Return the FS test server hostnames passed via the
    `--fshost` cmd line arg.
    '''
    argstring = request.config.option.fshost
    if not argstring:
        pytest.skip("the '--fshost' option is required to determine the "
                    "FreeSWITCH slave server(s) to connect to for testing")
    # construct a list if passed as arg
    fshosts = argstring.split(',')
    return fshosts


@pytest.fixture(scope='session')
def fs_ip_addrs(fshosts):
    '''Convert provided host names to ip addrs via dns.
    '''
    return list(map(ncompose(socket.gethostbyname, socket.getfqdn), fshosts))


@pytest.fixture(scope='session')
def fs_socks(request, fshosts):
    '''Return the fshost,fsport values as tuple (str, int).
    Use port 5080 (fs external profile) by default.
    '''
    return list(zip(fshosts, itertools.repeat(request.config.option.fsport)))


@pytest.fixture(scope='session')
def fshost(fshosts):
    return fshosts[0]


@pytest.fixture(scope='module')
def fsip(fs_ip_addrs):
    return fs_ip_addrs[0]


@pytest.fixture(scope='module')
def fssock(fs_socks):
    return fs_socks[0]


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


@pytest.yield_fixture
def client(fshost):
    """Deliver a core.Client connected to fshost
    """
    from switchy import Client
    cl = Client(fshost)
    yield cl
    cl.disconnect()
    assert not cl.connected()


@pytest.fixture
def scenarios(request, fs_socks, loglevel):
    '''Provision and return a SIPp scenario with the remote proxy set to the
    current FS server.
    '''
    sipp = spawn.find_executable('sipp')
    if not sipp:
        pytest.skip("SIPp is required to run call/speed tests")

    try:
        import pysipp
    except ImportError:
        pytest.skip("pysipp is required to run call/speed tests")

    pl = pysipp.utils.get_logger()
    pl.setLevel(loglevel)

    scens = []
    for fssock in fs_socks:
        # first hop should be fs server
        scen = pysipp.scenario(proxyaddr=fssock, logdir=tempfile.mkdtemp())
        scen.log = pl

        # set client destination
        # NOTE: you must add a park extension to your default dialplan!
        scen.agents['uac'].uri_username = 'park'
        scens.append(scen)

    return scens


@pytest.fixture
def scenario(scenarios):
    return scenarios[0]
