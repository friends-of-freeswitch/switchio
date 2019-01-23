switchio
========
``asyncio`` powered `FreeSWITCH`_ cluster control purpose-built on
`traffic theory`_ and `stress testing`_.

``switchio`` is a *fast* asynchronous control system for managing *FreeSWITCH* clusters.
It uses the *FreeSWITCH* ESL `inbound`_ protocol and was originally built for generating
traffic to stress test telephony service systems.


Installation
------------
::
    pip install switchio

Features
--------

- drive multiple *FreeSWITCH* processes (a cluster) from a single Python program
- build dialplan systems using a :ref:`flask-like` API and native `coroutines`_
- create cluster controllers using ``switchio`` :doc:`services <services>`
- generate traffic using the built-in :ref:`auto-dialer <callgen>`
- record, display and export CDR and performance metrics captured during stress tests
- use the internal ``asyncio`` inbound ESL `protocol`_ for lower level control

*FreeSWITCH* Configuration
**************************
``switchio`` relies on some simple :ref:`deployment <fsconfig>` steps for
import-and-go usage.


.. hyperlinks
.. _inbound:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-Inbound
.. _FreeSWITCH:
    https://freeswitch.org/confluence/display/FREESWITCH
.. _stress testing:
    https://en.wikipedia.org/wiki/Stress_testing
.. _traffic theory:
    https://en.wikipedia.org/wiki/Teletraffic_engineering
.. _protocol:
    https://github.com/friends-of-freeswitch/switchio/blob/master/switchio/protocol.py
.. _coroutines:
    https://docs.python.org/3/library/asyncio-task.html
.. _pandas:
    http://pandas.pydata.org/
.. _matplotlib:
    http://matplotlib.org/


User Guide
----------
.. toctree::
    :maxdepth: 1

    fsconfig
    quickstart
    services
    callgen
    apps
    cmdline
    sessionapi
    usage
    api
    testing


.. Indices and tables
   ==================
   * :ref:`genindex`
   * :ref:`modindex`
   * :ref:`search`
