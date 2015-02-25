Switchy
=======
Fast `FreeSWITCH`_ ESL control with an emphasis on **load testing**


Overview
--------
|  Switchy intends to be a fast control library for harnessing the power of
   the *FreeSWITCH* telephony engine whilst leveraging the expressiveness of
   python.
|  It relies on the *FreeSWITCH* ESL `inbound method <inbound>`_
   for control and was originally created for load testing using *FreeSWITCH*
   :term:`slave` clusters.


Features
--------
Among other things, Switchy lets you

- Drive `N` :term:`slaves <slave>` as a call generation cluster
- Write call control applications in pure python using a super thin ESL
  api wrapper
- Collect real time per-call performance metrics - **requires numpy**
- Dynamically modify call flows at runtime - **coming soon**


Installation
------------
See instructions on the `github`_ page.


Dependencies
************
|  For now, Switchy relies on the `ESL SWIG python package`_ distributed
   with the *FreeSWITCH* sources.
|  It is generally recommended to build the ESL library stand-alone on the
   machine which will host Switchy and to deploy *FreeSWITCH* in its entirety
   on slave servers.

Optional Python dependencies include:

- :ref:`numpy` for performance measurement collection
- :ref:`matplotlib` for realtime metrics plotting (**coming soon**)
- :ref:`plumbum` for *zero deploy* provisioning of slave configurations (**coming soon**)


Configuration
*************
Switchy relies on baseline *FreeSWITCH* :ref:`deployment <fsconfig>` steps for
import-and-go usage

.. hyperlinks
.. _inbound:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-Inbound
.. _FreeSWITCH:
    https://freeswitch.org/confluence/display/FREESWITCH
.. _github:
    https://github.com/sangoma/switchy
.. _ESL SWIG python package:
    https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL

Contents
--------
.. toctree::
    :maxdepth: 1

    fsconfig
    usage
    callgen
    apps
    api
.. ::
    call-apps
    benchmarks
    testing


.. Indices and tables
   ==================
   * :ref:`genindex`
   * :ref:`modindex`
   * :ref:`search`

