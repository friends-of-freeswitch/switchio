# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os
import sys
import socket
import itertools
import pytest
from distutils import spawn
from switchio import utils


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
                     default=100,
                     help="num of sipp calls to launch per second")
    parser.addoption("--use-docker", action="store_true", dest='usedocker',
                     help="Toggle use of docker containers for testing")
    parser.addoption("--num-containers", action="store", dest='ncntrs',
                     default=2, help="Number of docker containers to spawn")


@pytest.fixture(scope='session')
def travis():
    return os.environ.get('TRAVIS', False)


@pytest.fixture(scope='session', autouse=True)
def loglevel(request):
    level = max(40 - request.config.option.verbose * 10, 5)
    if sys.stdout.isatty():
        # enable console logging
        utils.log_to_stderr(level)

    return level


@pytest.fixture(scope='session', autouse=True)
def log(loglevel):
    return utils.log_to_stderr(loglevel)


@pytest.fixture(scope='session')
def projectdir():
    dirname = os.path.dirname
    return os.path.abspath(dirname(dirname(os.path.realpath(__file__))))


@pytest.fixture(scope='session')
def containers(request, projectdir):
    """Return a sequence of docker containers.
    """
    freeswitch_conf_dir = os.path.join(projectdir, 'conf/ci-minimal/')
    freeswitch_sounds_dir = os.path.join(projectdir, 'freeswitch-sounds/')
    if request.config.option.usedocker:
        docker = request.getfixturevalue('dockerctl')
        with docker.run(
            'safarov/freeswitch:latest',
            volumes={
                freeswitch_conf_dir: {'bind': '/etc/freeswitch/'},
                freeswitch_sounds_dir: {'bind': '/usr/share/freeswitch/sounds'},
            },
            environment={'SOUND_RATES': '8000:16000',
                         'SOUND_TYPES': 'music:en-us-callie'},
            num=request.config.option.ncntrs
        ) as containers:
            yield containers
    else:
        pytest.skip(
            "You must specify `--use-docker` to activate containers")


@pytest.fixture(scope='session')
def fshosts(request, log):
    '''Return the FS test server hostnames passed via the
    ``--fshost`` cmd line arg.
    '''
    argstring = request.config.option.fshost
    addrs = []

    if argstring:
        # construct a list if passed as arg
        fshosts = argstring.split(',')
        yield fshosts

    elif request.config.option.usedocker:
        containers = request.getfixturevalue('containers')
        for container in containers:
            ipaddr = container.attrs['NetworkSettings']['IPAddress']
            addrs.append(ipaddr)
            log.info(
                "FS container @ {} access: docker exec -ti {} fs_cli"
                .format(ipaddr, container.short_id)
            )
        yield addrs

    else:
        pytest.skip("the '--fshost' or '--use-docker` options are required "
                    "to determine the FreeSWITCH server(s) to connect "
                    "to for testing")


@pytest.fixture(scope='session')
def fs_ip_addrs(fshosts):
    '''Convert provided host names to ip addrs via dns.
    '''
    return list(map(utils.ncompose(
                socket.gethostbyname, socket.getfqdn), fshosts))


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
def cps(request, travis):
    """It appears as though fs can deliver channel create events at
    around 250 cps (don't know if we can even track faster
    then this) IF the calls are bridged directly using an xml
    dialplan (can get close with a pure esl dp and a fast server).
    Bridging them using the proxy_dp fixture above we can only
    get around 165 for slow servers...
    """
    cps = int(request.config.option.cps)
    return cps if not travis else 80


@pytest.yield_fixture
def con(fshost):
    '''Deliver a esl connection to fshost
    '''
    from switchio.connection import get_connection
    with get_connection(fshost) as con:
        yield con


@pytest.yield_fixture
def el(fshost):
    'deliver a connected event listener'
    from switchio import get_listener
    listener = get_listener(fshost)
    el = listener.event_loop
    assert not el.connected()
    yield listener
    el.disconnect()
    # verify state
    assert not el.connected()
    assert not el.is_alive()


@pytest.yield_fixture
def client(fshost):
    """Deliver a core.Client connected to fshost
    """
    from switchio import Client
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

    if request.config.option.usedocker:
        # use the docker 'bridge' network gateway address
        bind_addr = request.getfixturevalue(
            'containers')[0].attrs['NetworkSettings']['Gateway']
    else:
        # grab IP from DNS lookup
        bind_addr = socket.getaddrinfo(
            socket.getfqdn(), 0, socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]

    scens = []
    for fssock in fs_socks:
        # first hop should be fs server
        scen = pysipp.scenario(
            proxyaddr=fssock,
            defaults={'local_host': bind_addr}
        )
        scen.log = pl

        # set client destination
        # NOTE: you must add a park extension to your default dialplan!
        scen.agents['uac'].uri_username = 'park'
        scens.append(scen)

    return scens


@pytest.fixture
def scenario(scenarios):
    return scenarios[0]
