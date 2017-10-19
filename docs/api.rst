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
A thread safe (plus more) wrapper around the ESL SWIG module's
`ESLConnection` type is found in
:doc:`connection.py <api/connection>`.


Observer components
-------------------
The core API :py:class:`~switchio.api.Client`
interface can be found in :doc:`api.py <api/observe>`.
There are also some synchronous helpers hidden within.


Call Control Apps
-----------------
All the :doc:`built in apps <api/apps>` can be found in the
:py:mod:`switchio.apps` subpackage.


.. _modelapi:

Model types
-----------
| The :doc:`api/models` api holds automated wrappers for interacting with different
  *FreeSWITCH* channel and session objects as if they were local
  instances.

* :py:class:`~switchio.models.Session` - represents a *FreeSWITCH*
  `session` entity and provides a rich method api for control using
  `call management commands`_.
* :py:class:`~switchio.models.Job` - provides a synchronous interface for
  background job handling.

.. _call management commands:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_commands#mod_commands-CallManagementCommands


.. _clustertools:

Cluster tooling
---------------
Extra helpers for managing a *FreeSWITCH* process cluster.

* :py:class:`~switchio.distribute.MultiEval` - Invoke arbitrary python
  expressions on a collection of objects.
* :py:class:`~switchio.distribute.SlavePool` - a subclass which adds
  oberver component helper methods.
