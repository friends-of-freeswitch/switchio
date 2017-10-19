"""
Apps testing
"""
import pytest
import switchio


@pytest.yield_fixture
def get_orig(request, fsip):
    '''An `Originator` factory which delivers instances configured to route
    calls back to the originating sip profile (i.e. in "loopback").
    '''
    origs = []

    def factory(userpart, port=5080, limit=1, rate=1, offer=1, **kwargs):
        orig = switchio.get_originator(
            fsip,
            limit=limit,
            rate=rate,
            max_offered=offer,
            **kwargs
        )

        # each profile should originate calls back to itself
        # to avoid dependency on another server
        orig.pool.evals(
            ("""client.set_orig_cmd('{}@{}:{}'.format(
             userpart, client.host, port), app_name='park')"""),
            userpart=userpart,
            port=port,
        )
        origs.append(orig)
        return orig

    yield factory
    for orig in origs:
        orig.shutdown()
