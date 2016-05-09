switchy
=======
Fast `FreeSWITCH`_ control purpose-built upon `traffic theory`_ for `stress testing`_.

Overview
--------
Switchy intends to be a fast control library for harnessing the power of
the *FreeSWITCH* telephony engine whilst leveraging the expressiveness of
Python. It relies on the *FreeSWITCH* ESL `inbound`_ method
for control and was originally created for stress testing using *FreeSWITCH*
:term:`slave` clusters.


Features
--------
Among other things, Switchy lets you

- Drive multiple FreeSWITCH processes as a call generator cluster
- Write call control applications (IVRs, auto-dialers, etc.) in pure
  Python using a thin ESL api wrapper
- Record and display performance metrics captured during stress tests


Installation
------------
See instructions on the `github`_ page.


Dependencies
************
For now, Switchy relies on the `ESL SWIG python package`_ distributed
with the *FreeSWITCH* sources. Luckily, a stable setuptools packaged
version has been `cobbled together by Sangoma
<https://github.com/sangoma/python-ESL>`_.

Optional Python dependencies include:

- `numpy` for performance measurement collection
- `matplotlib` for metrics plotting
- `pytest` for running the unit test suite


FreeSWITCH Configuration
************************
Switchy relies on some baseline *FreeSWITCH* :ref:`deployment <fsconfig>` steps for
import-and-go usage


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


Contents
--------
.. toctree::
    :maxdepth: 1

    fsconfig
    quickstart
    callgen
    usage
    apps
    testing
    api


.. Indices and tables
   ==================
   * :ref:`genindex`
   * :ref:`modindex`
   * :ref:`search`
