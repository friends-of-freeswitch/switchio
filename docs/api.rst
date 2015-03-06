.. toctree::
    :maxdepth: 1
    :hidden:

    api/observe
    api/models
    api/distribute


API Reference
=============
This reference is not entirely comprehensive and is expected to change.


Observer components
-------------------
| The core event processing loop and logic and
  :py:class:`~switchy.observe.Client` interface can be found
  in :doc:`observe.py <api/observe>`.
| There are also some synchronous mechanisms hidden within.


.. _modelapi:

Model types
-----------
| The :doc:`api/models` api holds automated wrappers for interacting with different
  *FreeSWITCH* channel and session objects as if they were local
  instances.

* :py:class:`~switchy.models.Session` - represents a *FreeSWITCH*
  `session` entity and provides a rich method api for control using
  `call management commands`_
* :py:class:`~switchy.models.Job` - provides a synchronous interface for
  background job handling

.. _call management commands:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_commands#mod_commands-CallManagementCommands

.. _clustertools:

Cluster tooling
---------------
Extra helpers for managing a *FreeSWITCH* process cluster.

* :py:class:`~switchy.distribute.MultiEval` - Invoke arbitrary python
  expressions on a collection of objects
* :py:class:`~switchy.distribute.SlavePool` - a subclass which adds
  oberver component helper methods
