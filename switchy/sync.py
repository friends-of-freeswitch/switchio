# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Make calls synchronously
"""
from contextlib import contextmanager
from switchy.apps.players import TonePlay
from switchy.api import get_client


@contextmanager
def sync_caller(host, port='8021', password='ClueCon',
                apps={'TonePlay': TonePlay}):
    '''Deliver a provisioned synchronous caller function.

    A caller let's you make a call synchronously returning control once
    it has entered a stable state. The caller returns the active originating
    `Session` and a `waitfor` blocker method as output.
    '''
    with get_client(host, port=port, auth=password, apps=apps) as client:

        def caller(dest_url, app_name, timeout=30, waitfor=None,
                   **orig_kwargs):
            # override the channel variable used to look up the intended
            # switchy app to be run for this call
            if caller.app_lookup_vars:
                client.listener.app_id_vars.extend(caller.app_lookup_vars)

            job = client.originate(dest_url, app_id=app_name, **orig_kwargs)
            job.get(timeout)
            if not job.successful():
                raise job.result
            call = client.listener.sessions[job.sess_uuid].call
            orig_sess = call.first  # first sess is the originator
            if waitfor:
                var, time = waitfor
                client.listener.event_loop.waitfor(orig_sess, var, time)

            return orig_sess, client.listener.event_loop.waitfor

        # attach apps handle for easy interactive use
        caller.app_lookup_vars = []
        caller.apps = client.apps
        caller.client = client
        caller.app_names = client._apps.keys()
        yield caller
