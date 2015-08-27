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
    ++ <param name="context" value="switchy"/>


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

When testing FreeSWITCH you will typically want to raise the max-sessions
and sessions-per-second parameters in autoload_configs/switch.conf.xml::

    <param name="max-sessions" value="20000"/>
    <!--Most channels to create per second -->
    <param name="sessions-per-second" value="1000"/>

This avoids FreeSWITCH to start rejecting calls for high loads. However, if your intention
is to see how FreeSWITCH behaves when reaches those parameters limits, you can set them to
a value that suits those purposes.

In order to reduce load due to logging it's recommended you reduce your core logging level. This is
also done in autoload_configs/switch.conf.xml::

    <!-- Default Global Log Level - value is one of debug,info,notice,warning,err,crit,alert -->
    <param name="loglevel" value="warning"/>

You will want to also raise the file descriptor count::

  # ulimit -n 1000000

You have to make this in the same shell where you start FreeSWITCH. This ensures FreeSWITCH will not
run out of file descriptors when making hundreds of calls.

For more information see *FreeSWITCH* `dialplans`_ and `performance`_

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
.. _performance:
    https://freeswitch.org/confluence/display/FREESWITCH/Performance+Testing+and+Configurations
