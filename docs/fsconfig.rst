.. _fsconfig:

*FreeSWITCH* configuration and deployment
-----------------------------------------
*switchy* relies on some basic *FreeSWITCH* configuration steps in order to enable
remote control via the `ESL inbound method`_.
Most importantly, the ESL configuration file must be modified to listen
on a known socket of choice and a *park-only* extension must be added to
*FreeSWITCH*'s `XML dialplan`_. *switchy* comes packaged with an example
:ref:`park only dialplan <parkonly>` which you can copy-paste into your
existing server(s).


Event Socket
++++++++++++
In order for *switchy* to talk to *FreeSWITCH* you must `enable ESL`_ to listen on all
IP addrs at port `8021`.  This can configured by simply making the following change to
the ``${FS_CONF_ROOT}/conf/autoload_configs/event_socket.conf.xml`` configuration file::

   -- <param name="listen-ip" value="127.0.0.1"/>
   ++ <param name="listen-ip" value="::"/>

Depending on your FS version, additional `acl configuration`_ may be required.


.. _parkonly:

Park only dialplan
++++++++++++++++++
An XML dialplan `extension`_ which places all *inbound* sessions into the
`park`_ state should be added to all target *FreeSWITCH* servers you wish to control with
*switchy*. An example `context`_ (``switchydp.xml``) is included in the `conf`_ directory
of the source code.  If using this file you can enable *switchy* to control all calls
received by a particular *FreeSWITCH* `SIP profile`_ by setting the ``"switchy"`` context.

As an example you can modify *FreeSWITCH*'s default `external`_ profile found
at ``${FS_CONF_ROOT}/conf/sip_profiles/external.xml``::

    <!-- Contents of  -->
    -- <param name="context" value="public"/>
    ++ <param name="context" value="switchy"/>

.. note::
    You can also add a park extension to your existing dialplan such that
    only a subset of calls relinquish control to *switchy* (especially
    useful if you'd like to test on an extant production system).


Configuring software under test
+++++++++++++++++++++++++++++++
For (stress) testing, the system under test should be configured to route calls back
to the originating *FreeSWITCH* (cluster) such that the originator hosts both the
*caller* and *callee* user agents (potentially using the same `SIP profile`_)::

    FreeSWITCH cluster                   Target test network or
                                         device

    --------------   outbound sessions   ---------------------
    | Originator | --------------------> | Device under test |
    |            | <-------------------- |   (in loopback)   |
    --------------   inbound sessions    ---------------------


This allows *switchy* to perform *call tracking* (associate *outbound* with *inbound*
SIP sessions) and thus assume full control of call flow as well as measure signalling
latency and other teletraffic metrics.


.. _proxydp:

Example *proxy* dialplan
========================
If your system to test is simply another *FreeSWITCH* instance then it is
highly recommended to use a *"proxy"* dialplan to route SIP sessions back
to the originator (caller)::

    <!-- Proxy Dialplan - forward calls to requested destination -->
    <condition field="${sip_req_uri}" expression="^(.+)$">
        <action application="bridge" data="sofia/${sofia_profile_name}/${sip_req_uri}"/>
    </condition>

.. note::
    This could have alternatively be implemented as a *switchy* :ref:`app <proxyapp>`.


Configuring FreeSWITCH for stress testing
=========================================
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


.. _ESL inbound method:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-Inbound
.. _XML dialplan:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan
.. _extension:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-Extensions
.. _context:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-Context
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
.. _enable ESL:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-Configuration
.. _acl configuration:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-ACL 
.. _raise the file descriptor count:
    https://freeswitch.org/confluence/display/FREESWITCH/Performance+Testing+and+Configurations#PerformanceTestingandConfigurations-RecommendedULIMITsettings
