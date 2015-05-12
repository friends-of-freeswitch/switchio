.. _callgen:
.. toctree::
    :maxdepth: 2
    :hidden:

    api

Call generation and load testing
--------------------------------
|   Switchy enables you to drive multiple switch instances as a call
    generation cluster.

Once you have a set of slave servers :ref:`deployed <fsconfig>`,
have started :program:`freeswitch` processes on each slave **and**
have configured the *ESL* to listen on the default *8021* port, simply
load the originator app passing in a sequence of slave server host names::

    >>> from switchy import get_originator
    >>> originator = get_originator(['hostnameA', 'hostnameB', 'hostnameC'])
    ...
    # Log messages should show on console describing connections and app initializations
    ...

    >>> originator
     <Originator: '0' active calls, state=[INITIAL], rate=30 limit=1 max_sessions=inf duration=10.0333333333>

.. note::
    If using ESL ports different then the default *8021*, simply pass
    a sequence of `(host, port)` socket pairs to the
    :py:class:`~switchy.apps.call_gen.get_originator` factory

|   Now we have a binding to an :py:class:`~switchy.apps.call_gen.Originator`
    instance which is a non-blocking Switchy :doc:`application <apps>` allowing us
    to originate calls from our *FreeSWITCH* cluster.

|   Notice the load settings such as `rate`, `limit` and `duration` shown in the
    output of the originator's :py:func:`__repr__` method.
|   These parameters determine the degree of load which will be
    originated from the cluster to your target :term:`intermediary` and
    downstream :term:`callee` systems.

|   In order to ensure that calls are made successfully it is recommended that
    the :term:`intermediary` system :ref:`loop calls back <proxydp>` to the
    originating slave server's :term:`caller`.
|   This allows switchy to associate *outbound* and *inbound*
    SIP sessions into calls. As an example if the called system is another
    FreeSWITCH server under test then you can configure a :ref:`proxy
    dialplan <proxydp>`.

A single slave generator
************************
For simplicity's sake let's assume for now that we only wish to use
**one** *FreeSWITCH* slave as a call generator. This simplifies the following steps
which otherwise require the more advanced :py:mod:`switchy.distribute` module's
cluster helper components for orchestration and config of call routing.
That is, assume for now we only passed `'vm-host'` to the originator factory
function above.

To ensure all systems in your test environment are configured correctly
try launching a single call (by keeping `limit=1`) and verify that it connects
and stays active::

    >>> originator.start()
    Feb 24 12:59:14 [ERROR] switchy.Originator@['vm-host'] call_gen.py:363 : 'MainProcess' failed with:
    Traceback (most recent call last):
      File "sangoma/switchy/apps/call_gen.py", line 333, in _serve_forever
          "you must first set an originate command")
    ConfigurationError: you must first set an originate command

Before we can start loading we must set the command which will be used by the
application when instructing each slave to `originate` a call. Note that the error
above was not raised as a Python exception but instead just printed to the screen to
avoid terminating the event processing loop in the :py:class:`switchy.observe.EventListener`.

Let's set an originate command which will call our :term:`intermediary`
as it's first hop with a destination of ourselves using the default
*external* profile and the *FreeSWITCH* built in *park* application for
the outbound session's post-connect execution::

    >>> originator.clients[0].set_orig_cmd(
        dest_url='doggy@hostnameA:5080,
        profile='external',
        app_name='park',
        proxy='doggy@intermediary_hostname:5060',
    )
    >>> originator.originate_cmd  # show the rendered command str
    ['originate {{originator_codec=PCMU,switchy_client={app_id},
    originate_caller_id_name=Mr_Switchy,originate_timeout=60,absolute_codec_string=,
    sip_h_X-originating_session_uuid={uuid_str},sip_h_X-switchy_client={app_id},
    origination_uuid={uuid_str}}}sofia/external/doggy@hostnameA:5060;
    fs_path=sip:goodboy@intermediary_hostname:5060 &park()']

The underlying `originate`_ command has now been
set for the **first** client in the `Orignator` app's client pool. You might
notice that the command is a :py:class:`format` string which has some
placeholder variables set. It is the job of the :py:class:`switchy.observe.Client`
to fill in these values at runtime (i.e. when the :py:meth:`switchy.observe.Client.originate` is called).
For more info on the `originate` cmd wrapper see :py:func:`~switchy.commands.build_originate_cmd`.
Also see :doc:`usage`.

Try starting again::

    >>> originator.start()
    Feb 24 14:12:35 [INFO] switchy.Originator@['vm-host'] call_gen.py:395 : starting loop thread
    Feb 24 14:12:35 [INFO] switchy.Originator@['vm-host'] call_gen.py:376 : State Change: 'INITIAL' -> 'ORIGINATING'

At this point there should be one active call from your :term:`caller`
(bridged) through the :term:`intermediary` and then received by the
:term:`callee`. You can check the :py:class:`Originator` status via it's
:py:meth:`__repr__` again::

    >>> originator
    <Originator: '1' active calls, state=[ORIGINATING], rate=30 limit=1 max_sessions=inf duration=10.0333333333>

.. warning::
    If you start seeing immediate errors such as::

        Feb 24 14:12:35 [ERROR] switchy.EventListener@vm-host observe.py:730 : Job '16f6313e-bc59-11e4-8b27-1b3a3a6a886d' corresponding to session '16f8964a-bc59-11e4-9c96-74d02bc595d7' failed with:
        -ERR NORMAL_TEMPORARY_FAILURE

    it may mean your :term:`callee` isn't configured correctly. Stop the `Originator` and Check the *FreeSWITCH* slave's logs to debug.

The `Originator` will keep offering new calls indefinitely with `duration` seconds
allowing up to `limit`'s (in *erlangs*) worth of concurrent calls until stopped.
That is, continuous load is offered until you either `stop` or `hupall` calls.
You can verify this by ssh-ing to the slave and calling the `status`
command from `fs_cli`_.

You can now increase the call load parameters::

    >>> originator.rate = 50  # increase the call rate
    >>> originator.limit = 1000  # increase max concurrent call limit (erlangs)
    # wait approx. 3 seconds
    >>> originator
    <Originator: '148' active calls, state=[INITIAL], rate=50 limit=1000 max_sessions=inf duration=30.0>

Note how the `duration` attribute was changed automatically. This is
because the `Originator` computes the correct *avergae call-holding time*
by the most basic `erlang formula`_. Feel free to modify the load parameters
in real-time as you please to suit your load test requirements.

Currently, the default Switchy app loaded by the `Originator` is :py:class:`switchy.apps.bert.Bert`
which provides a decent media *tranparency* test useful in auditting :term:`intermediary` DUTs.
This app requires that the `mod_bert` has been successfully initialized/loaded on the *FreeSWITCH* slave(s).

To tear down calls you can use one of :py:meth:`~switchy.apps.call_gen.Originator.stop` or
:py:meth:`~switchy.apps.call_gen.Originator.hupall`.  The former will simply stop the *burst*
loop and let calls slowly teardown as per the `duration` attr whereas the latter will forcefully
abort all calls associated with a given `Client`::

    >>> originator.hupall()
    Feb 24 16:37:16 [WARNING] switchy.Originator@['vm-host'] call_gen.py:425 : Stopping all calls with hupall!
    Feb 24 16:37:16 [INFO] switchy.Originator@['vm-host'] call_gen.py:376 : State Change: 'ORIGINATING' -> 'STOPPED'
    Feb 24 16:37:16 [INFO] switchy.Originator@['vm-host'] call_gen.py:357 : stopping burst loop...
    Feb 24 16:37:16 [INFO] switchy.Originator@['vm-host'] call_gen.py:326 : Waiting for start command...
    Feb 24 16:37:16 [ERROR] switchy.EventListener@vm-host observe.py:730 : Job '4d8823c4-bc6d-11e4-af92-1b3a3a6a886d' corresponding to session '4d837b3a-bc6d-11e4-9c2e-74d02bc595d7' failed with:
    -ERR NORMAL_CLEARING
    Feb 24 16:37:16 [ERROR] switchy.EventListener@vm-host observe.py:730 : Job '4d8f509a-bc6d-11e4-afa3-1b3a3a6a886d' corresponding to session '4d8aacb6-bc6d-11e4-9c2e-74d02bc595d7' failed with:
    -ERR NORMAL_CLEARING
    Feb 24 16:37:16 [INFO] switchy.Originator@['vm-host'] call_gen.py:231 : all sessions have ended...

When `hupall`-ing, a couple `'NORMAL_CLEARING'` errors are totally normal.


Slave cluster
*************
In order to deploy call generation clusters some slightly more advanced
configuration steps are required to properly provision the
:py:class:`switchy.apps.call_gen.Originator`. As mentioned previous,
this involves use of handy cluster helper components provided with
Switchy.

The main trick is to configure each :py:class:`switchy.observe.Client` to have
the appropriate originate command set such that calls are routed to
where you expect. A clever and succint way to accomplish this is by
using the :py:class:`switchy.distribute.SlavePool`. Luckily the
`Originator` app is built with one internally by default.

Configuration can now be done with something like::

    >>> originator.pool.evals(
        ("""client.set_orig_cmd('park@{}:5080'.format(client.server),
         app_name='park',
         proxy='doggy@{}:5060'.format(ip_addr))"""),
         ip_addr='intermediary_hostname.some.domain'
    )

This will result in each slave calling itself *through* the intermediary
system. The `pool.evals` method essentially allows you to invoke
arbitrary Python expressions across all slaves in the cluster.

For more details see :ref:`clustertools` .


Measurement collection
**********************
Given that you have `numpy` installed, the `Originator` collects call latency measurements
by default using the built-in :ref:`metrics <metricsapp>` app. The array
is referenced by the :py:attr:`switchy.apps.call_gen.Originator.metrics`
attribute::

    >>> originator.metrics
    array([
    (1431052903.824296, 0.01998305320739746, 0.0199739933013916, 0.05997896194458008, 0.01702594757080078, 0L, 1999L),
    (1431052903.864301, 0.0, 0.020053863525390625, 0.05999898910522461, 0.0016980171203613281, 0L, 1998L),
    (1431052903.884275, 0.019971132278442383, 0.019969940185546875, 0.05999493598937988, 0.007421970367431641, 0L, 1997L),
    ...,
    (1431053015.88425, 0.06000018119812012, 0.019997835159301758, 0.09999799728393555, 0.01164388656616211, 0L, 1934L),
    (1431053015.924249, 0.02000117301940918, 0.019997835159301758, 0.05999898910522461, 0.01691603660583496, 0L, 1933L),
    (1431053015.96425, 0.019997835159301758, 0.03999900817871094, 0.09999799728393555, 0.013684988021850586, 0L, 1932L)],
    dtype=[('time', '<f8'), ('invite_latency', '<f8'), ('answer_latency', '<f8'), ('call_setup_latency', '<f8'),
    ('originate_latency', '<f8'), ('num_failed_calls', '<u4'), ('num_sessions', '<u4')])

If you have `matplotlib` installed you can also plot the results using
:py:meth:`switchy.apps.call_gen.Originator.metrics.plot`.


.. _originate:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_commands#mod_commands-originate

.. _erlang formula:
    http://en.wikipedia.org/wiki/Erlang_%28unit%29#Traffic_measurements_of_a_telephone_circuit

.. _fs_cli:
    https://freeswitch.org/confluence/display/FREESWITCH/Command-Line+Interface+fs_cli
