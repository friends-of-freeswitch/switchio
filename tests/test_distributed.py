# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
test mult-slave control
'''
import pytest


@pytest.fixture(scope='module')
def pool():
    from switchy.apps.call_gen import get_pool
    # TODO: require this list from cli arg!!
    sp = get_pool([
        'vm-host.qa.sangoma.local',
        'sip-cannon.qa.sangoma.local',
    ])
    return sp


def test_setup(pool):
    from switchy.apps.bert import Bert
    from switchy import utils
    pool.evals('listener.unsubscribe("CALL_UPDATE")')
    assert not any(pool.evals('listener.connected()'))
    pool.evals('listener.connect()')
    assert all(pool.evals('listener.connected()'))
    # listener connects the client's con implicitly
    assert all(pool.evals('client.connected()'))
    pool.evals('client.load_app(Bert)', Bert=Bert)
    name = utils.get_name(Bert)
    assert all(False for apps in pool.evals('client._apps')
               if name not in apps)
    pool.evals('listener.start()')
    assert all(pool.evals('listener.is_alive()'))
