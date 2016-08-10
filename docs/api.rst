.. toctree::
    :maxdepth: 1
    :hidden:

    api/connection
    api/observe
    api/models
    api/distribute
    api/sync
    api/apps
    api/commands
    api/apps
    api/utils


API Reference
=============
.. note::
    This reference is not entirely comprehensive and is expected to change.


Connection wrapper
------------------
A thread safe (plus more) wrapper around the ESL swig module's
`ESLConnection` type is found in
:doc:`connection.py <api/connection>`.


Observer components
-------------------
The core event processing loop and logic and :py:class:`~switchy.observe.Client`
interface can be found in :doc:`observe.py <api/observe>`.
There are also some synchronous helpers hidden within.


Call Control Apps
-----------------
All the :doc:`built in apps <api/apps>` can be found in the
:py:mod:`switchy.apps` subpackage.


.. _modelapi:

Model types
-----------
| The :doc:`api/models` api holds automated wrappers for interacting with different
  *FreeSWITCH* channel and session objects as if they were local
  instances.

* :py:class:`~switchy.models.Session` - represents a *FreeSWITCH*
  `session` entity and provides a rich method api for control using
  `call management commands`_.
* :py:class:`~switchy.models.Job` - provides a synchronous interface for
  background job handling.

.. _call management commands:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_commands#mod_commands-CallManagementCommands


.. _clustertools:

Cluster tooling
---------------
Extra helpers for managing a *FreeSWITCH* process cluster.

* :py:class:`~switchy.distribute.MultiEval` - Invoke arbitrary python
  expressions on a collection of objects.
* :py:class:`~switchy.distribute.SlavePool` - a subclass which adds
  oberver component helper methods.
