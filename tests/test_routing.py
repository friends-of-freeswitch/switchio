# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Tests for routing apps.
'''
import pytest
from switchy import Service
from switchy.apps.routers import Router


@pytest.fixture
def router(fshost):
    """An inbound router which processes sessions from the `external`
    SIP profile.
    """
    return Router(guards={
        'Call-Direction': 'inbound',
        'variable_sofia_profile_name': 'external'
    })


@pytest.fixture
def service(fshost, router):
    """A switchy routing service.
    """
    s = Service([fshost])
    s.apps.load_app(router, app_id='default')
    return s


@pytest.mark.parametrize('did, expect', [('100', True), ('101', False)])
def test_routes(scenario, service, router, did, expect):
    """Test routing based on Request-URI user part patterns.
    """
    # route to the b-leg SIPp UAS
    router.route('100', field='Caller-Destination-Number')(
        router.bridge2dest)

    @router.route('101')
    def reject(sess, router, match):
        sess.respond('407')

    service.run(block=False)
    assert service.is_alive()
    scenario.agents['uac'].uri_username = did
    if expect:
        scenario()
    else:
        with pytest.raises(RuntimeError):
            scenario()
