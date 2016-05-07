.. _fsconfig:

*FreeSWITCH* configuration and deployment
-----------------------------------------
Switchy relies on some basic configuration steps to be completed on
slave servers such that *FreeSWITCH* can be controlled via the ESL
:ref:`inbound method <inbound>` .
Most importantly, the ESL configuration file must be modified to listen
on a known socket of choice (or on all addrs and the default
port if you're lazy).
Additionally, it is recommended to use the provided :ref:`park only dialplan <parkonly>`
packaged with Switchy to enable full control over ESL.


Configuring :term:`originating <originator>` and :term:`called <callee>` slave servers
**************************************************************************************
The following configurations are highly recommended for *FreeSWITCH*
instances which will host both :term:`callers <caller>` and :term:`callees
<callee>`.


Event Socket
++++++++++++

By default, Switchy expects that you have `enabled ESL`_ to listen on all ip addrs at port `8021`.
This can usually be done by simply making the following change to the following *FreeSWITCH* 
configuration file:

`${FS_CONF_ROOT}/conf/autoload_configs/event_socket.conf.xml`::

   -- <param name="listen-ip" value="127.0.0.1"/>
   ++ <param name="listen-ip" value="::"/>

Depending on your FS version, additional `acl configuration`_ may be required.


.. _parkonly:

Park only dialplan (*switchydp.xml*)
++++++++++++++++++++++++++++++++++++
A an XML dialplan which places all inbound sessions into the `park`_ state is
included in the `conf`_ directory of the package sources and must be uploaded
to all *FreeSWITCH* :term:`slave` servers which will be used for processing
calls using Switchy. Any Switchy controlled *FreeSWITCH* SIP profiles must set
their dialplan *context* to this `"switchy"` dialplan context name:

As an example using *FreeSWITCH*'s provided `external`_ profile::

    <!-- Contents of ${FS_CONF_ROOT}/conf/sip_profiles/external.xml -->
    -- <param name="context" value="public"/>
    ++ <param name="context" value="switchy"/>


Configuring the :term:`intermediary` server or 'softwares under test'
*********************************************************************
For testing, the :term:`intermediary` user agent should be configured to route calls back
to the originating *FreeSWITCH* slave such that the originator hosts both the
:term:`caller` **and** :term:`callee` (potentially using the same `SIP profile`_)

This allows Switchy to perform *call tracking* (associate *outbound* with *inbound*
SIP sessions) and thus assume full control of call flow in test applications as
well as capture measurements of signalling latencies and other teletraffic metrics.


.. _proxydp:

Example 'proxy' dialplan for stress testing an :term:`intermediary` *FreeSWITCH*
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
If your system to test (the :term:`intermediary`) is simply another *FreeSWITCH*
server then it is highly recommended to use a simple *"proxy"* dialplan
to route SIP sessions back to the :term:`originator`::

    <!-- Proxy Dialplan - forward calls to requested destination -->
    <condition field="${sip_req_uri}" expression="^(.+)$">
        <action application="bridge" data="sofia/${sofia_profile_name}/${sip_req_uri}"/>
    </condition>

This could alternatively be implemented using a Switchy :ref:`app <proxyapp>`.


Configuring FreeSWITCH for stress testing
+++++++++++++++++++++++++++++++++++++++++
Before attempting to stress test *FreeSWITCH* itself be sure you've read  the
`performance`_  and `dialplans`_ sections of the wiki.

You'll typically want to raise the `max-sessions` and `sessions-per-second`
parameters in `autoload_configs/switch.conf.xml`::

    <param name="max-sessions" value="20000"/>
    <!-- Max channels to create per second -->
    <param name="sessions-per-second" value="1000"/>

This prevents *FreeSWITCH* from rejecting calls at high loads. However, if your intention
is to see how *FreeSWITCH* behaves at those parameters limits, you can always set values
that suit those purposes.

In order to reduce load due to logging it's recommended you reduce your core logging level.
This is also done in `autoload_configs/switch.conf.xml`::

    <!-- Default Global Log Level - value is one of debug,info,notice,warning,err,crit,alert -->
    <param name="loglevel" value="warning"/>

You will also probably want to `raise the file descriptor count`_.

.. note::
    You have to run `ulimit` in the same shell where you start a *FreeSWITCH*
    process.


Routing Diagram
***************
When stress testing the recommended routing to employ roughly diagrams to
something like::

    FreeSWITCH slave(s)                  Device under test

    --------------   outbound sessions   -----------------
    | Originator | --------------------> | Intermediary  |
    |            | <-------------------> | (in loopback) |
    --------------   inbound sessions    -----------------


.. note::
    TODO: get a nice diagram here!

.. _park:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_dptools:+park
.. _SIP profile:
    https://freeswitch.org/confluence/display/FREESWITCH/Configuring+FreeSWITCH#ConfiguringFreeSWITCH-SIPProfiles
.. _dialplans:
    https://freeswitch.org/confluence/display/FREESWITCH/Configuring+FreeSWITCH#ConfiguringFreeSWITCH-Dialplan
.. _performance:
    https://freeswitch.org/confluence/display/FREESWITCH/Performance+Testing+and+Configurations
.. _conf:
    https://github.com/sangoma/switchy/tree/master/conf
.. _external:
    https://freeswitch.org/confluence/display/FREESWITCH/Configuring+FreeSWITCH#ConfiguringFreeSWITCH-External
.. _enabled ESL:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-Configuration
.. _acl configuration:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-ACL 
.. _raise the file descriptor count:
    https://freeswitch.org/confluence/display/FREESWITCH/Performance+Testing+and+Configurations#PerformanceTestingandConfigurations-RecommendedULIMITsettings
