.. toctree::
    :maxdepth: 2
    :hidden:

    api


Quick-Start - Originating a single call
=======================================
Assuming you've gone through the required :doc:`deployment steps
<fsconfig>` to setup at least one slave, initiating a call becomes
very simple using the Switchy command line::

    $ switchy run vm-host sip-cannon --profile external --proxy myproxy.com --rate 1 --limit 1 --max-offered 1

    ...

    Aug 26 21:59:01 [INFO] switchy cli.py:114 : Slave sip-cannon.qa.sangoma.local SIP address is at 10.10.8.19:5080
    Aug 26 21:59:01 [INFO] switchy cli.py:114 : Slave vm-host.qa.sangoma.local SIP address is at 10.10.8.21:5080
    Aug 26 21:59:01 [INFO] switchy cli.py:120 : Starting load test for server dut-008.qa.sangoma.local at 1cps using 2 slaves
    <Originator: active-calls=0 state=INITIAL total-originated-sessions=0 rate=1 limit=1 max-offered=1 duration=5>

    ...

    <Originator: active-calls=1 state=STOPPED total-originated-sessions=1 rate=1 limit=1 max-offered=1 duration=5>
    Waiting on 1 active calls to finish
    Waiting on 1 active calls to finish
    Waiting on 1 active calls to finish
    Waiting on 1 active calls to finish
    Load test finished!


The Switchy `run` sub-command takes several options and a list
of slaves (or at least one) IP address or hostname. In this
example switchy connected to the specified slaves, found the specified SIP
profile and initiated a single call with a duration of 5 seconds to the
device under test (set with the `proxy` option).

For more information on the switchy command line see :doc:`here <cmdline>`.


Originating a single call programatically from Python
-----------------------------------------------------
Making a call with switchy is quite simple using the built-in
:py:func:`~switchy.sync.sync_caller` context manager.
Again, if you've gone through the required :doc:`deployment steps
<fsconfig>`, initiating a call becomes as simple as a few lines of python
code

.. code-block:: python
    :linenos:

    from switchy import sync_caller
    from switchy.apps.players import TonePlay

    # here '192.168.0.10' would be the address of the server running a
    # FS process to be used as the call generator
    with sync_caller('192.168.0.10', apps={"tone": TonePlay}) as caller:

        # initiates a call to the originating profile on port 5080 using
        # the `TonePlay` app and block until answered / the originate job completes
        sess, waitfor = caller('Fred@{}:{}'.format(caller.client.host, 5080), "tone")
        # let the tone play a bit
        time.sleep(5)
        # tear down the call
        sess.hangup()


The most important lines are the `with` statement and line 10.
What happens behind the scenes here is the following:

    * at the `with`, necessary internal Switchy components are instantiated in memory
      and connected to the :term:`slave` *FreeSWITCH* process listening on the `fsip`
      ESL ip address.
    * at the `caller()`, an :py:meth:`~switchy.observe.Client.originate` command is
      invoked asynchronously via a :py:meth:`~switchy.observe.Client.bgapi` call.
    * the background :py:class:`~switchy.models.Job` returned by that command is handled
      to completion **synchronously** wherein the call blocks until the originating session has
      reached the connected state.
    * the corresponding origininating :py:class:`~switchy.models.Session` is returned along with
      a reference to a :py:meth:`switchy.observe.EventListener.waitfor` blocker method.
    * the call is kept up for 1 second and then :py:meth:`hungup <switchy.models.Session.hangup>`.
    * internal Switchy components are disconnected from the :term:`slave` process at the close of
      the `with` block.

Note that the `sync_caller` api is not normally used for :doc:`stress testing <callgen>`
as it used to initiate calls *synchronously*. It becomes far more useful when using
*FreeSWITCH* for functional testing using your own custom call flow :doc:`apps <apps>`.


Example source code
-------------------
Some more extensive examples are found in the unit tests sources :

.. literalinclude:: ../tests/test_sync_call.py
    :caption: test_sync_call.py
    :linenos:


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
