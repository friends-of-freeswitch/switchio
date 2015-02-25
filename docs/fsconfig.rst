.. _fsconfig:

*FreeSWITCH* configuration and deployment
-----------------------------------------
|   Switchy relies on some basic configuration steps to be completed on
    slave servers such that *FreeSWITCH* can be controlled via the ESL
    :ref:`inbound method <inbound>` .
|   Most importantly, the ESL configuration file must be modified to listen
    on a known socket of choice (or on all addrs and the default
    port if you're lazy).
|   Additionally, it is recommended to use the provided :ref:`park only dialplan <parkonly>`
    packaged with Switchy to enable full Python based call control.


Configuring :term:`originating <originator>` and :term:`called <callee>` slave servers
**************************************************************************************
The following configurations are highly recommended for *FreeSWITCH*
instances which will host :term:`callers <caller>`/:term:`callees
<callee>`


Event Socket
++++++++++++

To enable ESL to be accessed from all ip addrs on port `8021`, simply make the
following change to the file:

`${FS_ROOT}/conf/autoload_configs/event_socket.conf.xml`::

   -- <param name="listen-ip" value="127.0.0.1"/>
   ++ <param name="listen-ip" value="0.0.0.0"/>

Eventually this step **should** be automated away through a *zero deploy* feature :o


.. _parkonly:

Park only dialplan - *switchydp.xml*
++++++++++++++++++++++++++++++++++++
|   A dialplan which puts all sessions into the `park`_ state is included
    with Switchy and can be found in the `conf` directory of the package
    sources.
|   For the *FreeSWITCH* profiles which will be used for the rx/tx
    of calls you must set the dialplan *context* to point to this `"switchy"`
    dialplan name:

As an example using *FreeSWITCH*'s provided `external` profile::

    <!-- Contents of ${FS_ROOT}/conf/sip_profiles/external.xml -->
    -- <param name="context" value="public"/>
    ++ <param name="context" value="switchydp"/>


Configuring the :term:`intermediary` server or 'softwares under test'
*********************************************************************
|   The :term:`intermediary` user agent should be configured to route calls back to the
    originating *FreeSWITCH* slave such that the originator hosts both the :term:`caller`
    **and** :term:`callee` (potentially using the same `sip profile`_)

|   This allows Switchy internals to easily associate *outbound* with *inbound* SIP sessions
    and thus assume full control of call flow applications as well as capture performance
    measurements of signalling and slave call generation latencies.


.. _proxydp:

Example 'proxy' dialplan for load testing an :term:`intermediary` *FreeSWITCH*
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
If your system to test (the :term:`intermediary`) is simply another *FreeSWITCH*
server then it is highly recommended to use a simple *"proxy"* dialplan
to route SIP sessions back to the :term:`originator`::

    <!-- Proxy Dialplan - forward calls to requested destination -->
    <condition field="${sip_req_uri}" expression="^(.+)$">
        <action application="bridge" data="sofia/${sofia_profile_name}/${sip_req_uri}"/>
    </condition>

This could alternatively be implemented using a :ref:`Switchy app <proxyapp>`

For more information see *FreeSWITCH* `dialplans`_

Typically for load testing this is the recommended routing to employ and
roughly diagrams to something like::

    FreeSWITCH slave(s)                  Device under test

    --------------   outbound sessions   -----------------
    | Originator | --------------------> | Intermediary  |
    |            | <-------------------> | (in loopback) |
    --------------   inbound sessions    -----------------

.. note::
    TODO: get a nice diagram here!

.. _park:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_dptools:+park
.. _sip profile:
    https://freeswitch.org/confluence/display/FREESWITCH/Configuring+FreeSWITCH#ConfiguringFreeSWITCH-SIPProfiles
.. _dialplans:
    https://freeswitch.org/confluence/display/FREESWITCH/Configuring+FreeSWITCH#ConfiguringFreeSWITCH-Dialplan
