switchy
=======
Fast `FreeSWITCH`_ control purpose-built upon `traffic theory`_ and `stress testing`_.

Overview
--------
Switchy intends to be a *fast* control library for harnessing the power of
the *FreeSWITCH* telephony engine whilst leveraging the expressiveness of
Python. It relies on the *FreeSWITCH* ESL `inbound`_ method
for control and was originally built for generating traffic using
*FreeSWITCH* :term:`slave` clusters.


Installation and Dependencies
-----------------------------
See instructions on the `github`_ page.

Features
--------

- drive multiple *FreeSWITCH* processes as a traffic generator
- write :doc:`services <services>` in pure Python to process flows from a *FreeSWITCH* cluster
- build a dialplan system using a :ref:`flask-like` API
- record, display and export CDR and performance metrics captured during stress tests
- async without requiring :code:`twisted`

*FreeSWITCH* Configuration
**************************
Switchy relies on some baseline server :ref:`deployment <fsconfig>` steps for
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
.. _github:
    https://github.com/sangoma/switchy
.. _ESL SWIG python package:
    https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL
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
