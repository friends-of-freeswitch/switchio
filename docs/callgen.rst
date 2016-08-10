.. _callgen:
.. toctree::
    :maxdepth: 2
    :hidden:

    api

Call generation and stress testing
----------------------------------
Switchy contains a built in auto-dialer which enables you to drive
multiple *FreeSWITCH* processes as a call generator cluster.

Once you have a set of slave servers :ref:`deployed <fsconfig>`,
have started :program:`FreeSWITCH` processes on each slave **and**
have configured the *ESL* to listen on the default *8021* port, simply
load the originator app passing in a sequence of slave server host names::

    >>> from switchy import get_originator
    >>> originator = get_originator(['hostnameA', 'hostnameB', 'hostnameC'])
    >>> originator
    <Originator: '0' active calls, state=[INITIAL], rate=30 limit=1
    max_sessions=inf duration=10.03>

.. note::
    If using ESL ports different then the default *8021*, simply pass
    a sequence of `(host, port)` socket pairs to the
    :py:class:`~switchy.apps.call_gen.get_originator` factory.

Now we have a binding to an :py:class:`~switchy.apps.call_gen.Originator`
instance which is a non-blocking Switchy :doc:`application <apps>` allowing us
to originate calls from our *FreeSWITCH* cluster.

Notice the load settings such as `rate`, `limit` and `duration` shown in the
output of the originator's :py:func:`__repr__` method. These parameters
determine the type of traffic which will be originated from the cluster
to your target :term:`intermediary` and downstream :term:`callee` systems.

In order to ensure that calls are made successfully it is recommended that
the :term:`intermediary` system :ref:`loop calls back <proxydp>` to the
originating slave server's :term:`caller`. This allows switchy to associate
*outbound* and *inbound* SIP sessions into calls. As an example if the called
system is another FreeSWITCH server under test then you can configure a
:ref:`proxy dialplan <proxydp>`.

A single call generator
***********************
For simplicity's sake let's assume for now that we only wish to use
**one** *FreeSWITCH* process as a call generator. This simplifies the following steps
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

Before we can start generating calls we must set the command which will be used by the
application when instructing each slave to `originate` a call. 

.. note::
    The error above was not raised as a Python exception but instead just printed to
    the screen to avoid terminating the event processing loop in the
    :py:class:`switchy.observe.EventListener`.

Let's set an originate command which will call our :term:`intermediary`
as it's first hop with a destination of *ourselves* using the default
*external* profile and the *FreeSWITCH* built in *park* application for
the outbound session's post-connect execution::

    >>> originator.pool.clients[0].set_orig_cmd(
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
Also see the :doc:`usage`.

Try starting again::

    >>> originator.start()
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
      File "switchy/apps/call_gen.py", line 479, in start
        raise utils.ConfigurationError("No apps have been loaded")
    switchy.utils.ConfigurationError: No apps have been loaded


We need to explicitly load a switchy :doc:`app <apps>` which will be
used to process originated (and possibly received) calls. For stress
testing the :py:class:`switchy.apps.bert.Bert` app is recommended as it
performs a stringent audio check alongside a traditional call flow using
`mod_bert`_::

    >>> from switchy.apps.bert import Bert
    >>> originator.load_app(Bert)

.. note::
    The `Originator` actually supports loading multiple (groups of) apps
    with different *weights* such that you can execute multiple call
    flows in parallel. This can be useful for simulating auto-dialer traffic::

        >>> from switchy.apps.blockers import CalleeRingback, CalleeBlockOnInvite
        >>> originator.load_app(CalleeRingback, ppkwargs={'caller_hup_after': 5, 'ring_response': 'ring_ready'}, weight=33)
        >>> originator.load_app(CalleeBlockonInvite, ppkwargs={'response': 404}, weight=33)
        >>> originator.load_app(Bert, weight=34)


Try starting once more::

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
because the `Originator` computes the correct *average call-holding time*
by the most basic `erlang formula`_. Feel free to modify the load parameters
in real-time as you please to suit your load test requirements.

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

When `hupall`-ing, a couple `NORMAL_CLEARING` errors are totally normal.


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

Configuration can now be done with something like:

.. code-block:: python

    originator.pool.evals(
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
By default, the `Originator` collects call detail records using the built-in
:ref:`CDR <cdrapp>` app. Given that you have `pandas`_ installed this data and
additional stress testing metrics can be accessed in `pandas` `DataFrames`_ via the
:py:attr:`switchy.apps.call_gen.Originator.measurers` object::

    >>> orig.measurers.stores.CDR
          switchy_app  hangup_cause     caller_create  caller_answer caller_req_originate  caller_originate  caller_hangup job_launch   callee_create  callee_answer  callee_hangup failed_calls  active_sessions  erlangs
    0     Bert         NORMAL_CLEARING  1.463601e+09   1.463601e+09  1.463601e+09          1.463601e+09      1.463601e+09  1.463601e+09 1.463601e+09   1.463601e+09   1.463601e+09  0             8                4
    1     Bert         NORMAL_CLEARING  1.463601e+09   1.463601e+09  1.463601e+09          1.463601e+09      1.463601e+09  1.463601e+09 1.463601e+09   1.463601e+09   1.463601e+09  0             12               6
    2     Bert         NORMAL_CLEARING  1.463601e+09   1.463601e+09  1.463601e+09          1.463601e+09      1.463601e+09  1.463601e+09 1.463601e+09   1.463601e+09   1.463601e+09  0             22               11
    3     Bert         NORMAL_CLEARING  1.463601e+09   1.463601e+09  1.463601e+09          1.463601e+09      1.463601e+09  1.463601e+09 1.463601e+09   1.463601e+09   1.463601e+09  0             6                3
    ...
    1056  Bert         NORMAL_CLEARING  1.463601e+09   1.463601e+09  1.463601e+09          1.463601e+09      1.463601e+09  1.463601e+09 1.463601e+09   1.463601e+09   1.463601e+09  0             1992             996

    >>> originator.measurers.ops.call_metrics
           active_sessions  answer_latency  avg_call_rate  call_duration \
    0      8                0.020000        NaN             20.880000
    1      12               0.020000        NaN             20.820000
    2      22               0.020000        NaN             20.660000
    3      2                0.020000        NaN             20.980000
    ...

           call_rate  call_setup_latency  erlangs  failed_calls  \
    0      25.000024  0.060000            4        0
    1      49.999452  0.060000            6        0
    2      50.000048  0.060000            11       0
    3      NaN        0.120000            1        0
    ...

If you have `matplotlib`_ installed you can also plot the results using
:py:meth:`Originator.measurers.plot`.

If you do not have have `pandas` installed then the CDR records are
still stored in a local `csv` file and can be read into a list of lists
using the same :py:attr:`orig.measurers.stores.CDR` attribute.

More to come...


.. _originate:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_commands#mod_commands-originate
.. _erlang formula:
    http://en.wikipedia.org/wiki/Erlang_%28unit%29#Traffic_measurements_of_a_telephone_circuit
.. _fs_cli:
    https://freeswitch.org/confluence/display/FREESWITCH/Command-Line+Interface+fs_cli
.. _mod_bert:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_bert
.. _pandas:
    http://pandas.pydata.org/pandas-docs/stable/
.. _DataFrames:
    http://pandas.pydata.org/pandas-docs/stable/dsintro.html#dataframe
.. _matplotlib:
    http://matplotlib.org/
