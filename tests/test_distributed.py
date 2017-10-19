# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
test mult-slave/cluster tools
'''
import pytest


@pytest.fixture(scope='module')
def pool(fshosts):
    if not len(fshosts) > 1:
        pytest.skip("the '--fshost' option must be a list of 2 or more "
                    "hostnames in order to run multi-slave tests")
    from switchio.api import get_pool
    return get_pool(fshosts)


def test_setup(pool):
    from switchio.apps.bert import Bert
    from switchio import utils
    pool.evals('listener.event_loop.unsubscribe("CALL_UPDATE")')
    assert not any(pool.evals('listener.connected()'))
    pool.evals('listener.connect()')
    assert all(pool.evals('listener.connected()'))
    pool.evals('client.connect()')
    pool.evals('client.load_app(Bert)', Bert=Bert)
    name = utils.get_name(Bert)
    assert all(False for apps in pool.evals('client._apps')
               if name not in apps)
    pool.evals('listener.start()')
    assert all(pool.evals('listener.is_alive()'))
    pool.evals('listener.disconnect()')
    assert not all(pool.evals('listener.is_alive()'))
