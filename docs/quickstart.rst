.. toctree::
    :maxdepth: 2
    :hidden:

    api


Quick-Start - Originating a single call
=======================================
| Making a call with Switchy is quite simple using the built-in
  :py:func:`~switchy.sync.sync_caller` context manager.
| Assuming you've gone through the required :doc:`deployment steps
  <fsconfig>`, initiating a call becomes as simple as 2 lines of python
  code.


Example source code
-------------------
An example is found in the unit tests sources :

.. literalinclude:: ../tests/test_sync_call.py
    :caption: test_sync_call.py
    :linenos:

The most important lines are the `with` statement and lines 17-21.
What happens behind the scenes here is the following:

    * necessary internal Switchy components are instantiated in memory
      and connected to the :term:`slave` *FreeSWITCH* process listening on
      the `fsip` ESL ip address
    * an :py:meth:`~switchy.observe.Client.originate` command is invoked asynchronously
      via a :py:meth:`~switchy.observe.Client.bgapi` call
    * the background :py:class:`~switchy.models.Job` returned by that command is handled
      to completion **synchronously** wherein the call blocks until the originating session has
      reached the connected state
    * the corresponding origininating :py:class:`~switchy.models.Session` is returned along with
      a reference to a :py:meth:`switchy.observe.EventListener.waitfor` blocker method.
    * the call is kept up for 1 second and then :py:meth:`hungup <switchy.models.Session.hangup>`
    * internal Switchy components are disconnected from the :term:`slave` process at the close of the `with` block


Run manually
************
You can run this code from the unit test directory quite simply::

    >>> from tests.test_sync_call import test_toneplay
    >>> test_toneplay('fs_slave_hostname')


Run with pytest
***************
If you have :ref:`pytest` installed you can run this test like so::

    $ py.test --fshost='fs_slave_hostname' tests/test_sync_caller


Implementation details
**********************
The implementation of :py:func:`~switchy.sync.sync_caller` is shown
below and can be referenced alongside the :doc:`usage` to gain a better
understanding of the inner workings of Switchy's api:

.. literalinclude:: ../switchy/sync.py
    :linenos:
