.. toctree::
    :maxdepth: 2
    :hidden:

    api


Quick-Start - Originating a single call
=======================================
Getting familiar with *Switchy*'s features means learning to put the
appropriate components together to generate a call. This simple guide is
meant to provide commentary along the way. It is assumed you are already
familiar with the prerequisite :doc:`deployment steps <fsconfig>`.


Components
----------
Currently there are 3 major core components for using Switchy to
drive *FreeSWITCH* which are:

:py:class:`~switchy.Connection` - essentially a thread safe wrapper around the
:ref:`SWIG module <ESL SWIG python package>`'s `ESLConnection`.

:py:class:`~switchy.Client` - contains a `Connection` providing additional
wrapper methods and state. Its most important feature set is providing an
interface for interacting with...

:py:class:`~switchy.EventListener` - the type that contains the core
event processing loop and logic. It is primarily concerned with
observing and tracking the state of a single *FreeSWITCH* process.
Normally you would want a one-to-one pairing of listeners to slave
processes/servers. Also contains a connection used mostly for
receiving events, only transmitting commands when dictated by :doc:`Switchy apps <apps>`.

For this guide we will focus on the latter 2 since they are high level
automated interfaces.


Using a `Client` and `EventListener` pair
-----------------------------------------
A Client is used for invoking or sending **synchronous** commands to the
*FreeSWITCH* process. It handles ESL `api` calls entirely on it's own.

To connect simply pass the hostname or ip address of the slave server at
instantiation::

    >>> from switchy import Client
    >>> client = Client('vm-host')
    >>> client.connect()
    >>> client.api('status')  # call ESL `api` command directly
    <ESL.ESLevent; proxy of <Swig Object of type 'ESLevent *' at 0x28c1d10> >

    >>> client.cmd('global_getvar local_ip_v4')  # `api` wrapper which returns event body content
    '10.10.8.21'

    >>> client.cmd('not a real command')
    Traceback (most recent call last):
        File "<stdin>", line 1, in <module>
        File "switchy/observe.py", line 1093, in cmd
           return self.api(cmd).getBody().strip()
        File "switchy/observe.py", line 1084, in api
           consumed, response = EventListener._handle_socket_data(event)
        File "switchy/observe.py", line 651, in _handle_socket_data
           raise CommandError(body)
    sangoma.switchy.utils.CommandError: -ERR not Command not found!

Cool. Ok let's initiate a call originating from the slave processe's
:term:`caller` which is by default the *external* sip profile::

    >>> client.originate(dest_url='9196@intermediary_hostname:5060')
    Traceback (most recent call last):
        File "<stdin>", line 1, in <module>
        File "switchy/observe.py", line 1177, in originate
            listener = self._assert_alive(listener)
        File "switchy/observe.py", line 1115, in _assert_alive
            assert self.listener, "No listener associated with this client"
        File "switchy/observe.py", line 973, in get_listener
            "No listener has been assigned for this client")
        AttributeError: No listener has been assigned for this client

The `Client` implements `originate` by making an **asynchronous** ESL
`bgapi` call to the slave process. In order to track the eventual
results of that call, an `EventListener` must be used which will
collect the state changes triggered by the command (i.e. as received in
event data from the slave process).

With this current architecture you can think of a *listener* as an object
from which you can read state and the *client* as interface which drives the
slave *FreeSWITCH* process using commands which trigger **new** state(s).
Again, any time a `Client` makes an **asynchronous** call an `EventListener` is
needed to handle and report back the result(s).

Let's create and assign an :py:class:`~switchy.EventListener`::

    >>> from switchy import get_listener
    >>> l = get_listener('vm-host')
    >>> l  # disconnected initially to allow for unsuscription from default event set
    <EventListener [disconnected]>
    >>> l.connect()
    Feb 25 10:33:05 [INFO] switchy.EventListener@vm-host observe.py:346 : Connected listener 'd2d4ee82-bd02-11e4-8b48-74d02bc595d7' to 'vm-host'
    >>> l
    <EventListener [connected]>
    >>> l.start()
    Feb 25 10:35:30 [INFO] switchy.EventListener@vm-host observe.py:287 : starting event loop thread
    >>> client.listener = l

.. note::
    Alternatively an `EventListener` can be passed to the `Client` at instatiation time as well


Now let's attempt our originate once more this time executing the *9197*
extension once the :term:`caller` is answered, and calling the `echo`
extension, *9196*, at the :term:`callee` end::

    >>> client.originate('9196@vm-host:5080',
        dp_exten=9197,
        proxy='intermediary_hostname:5060'
    )
    <sangoma.switchy.models.Job at 0x7feea01c6c90>

    >>> client.listener.calls  # check the active calls collection
    OrderedDict([('72451178-bd0c-11e4-9d26-74d02bc595d7', <Call(72451178-bd0c-11e4-9d26-74d02bc595d7, 2 sessions)>)])

.. note::
    See the *default* dialplan packaged with stock *FreeSWITCH*.
    Use of these extensions assumes you have assigned the *external* sip profile to use
    the *deafult* dialplan by assigning it's *context* parameter


The async `originate` call returns to us a :py:class:`switchy.models.Job` instance (as would any call to :py:meth:`switchy.Client.bgapi`).
A `Job` provides the same interface as that of the
:py:class:`multiprocessing.pool.AsyncResult` and can be handled to completion synchronously::

    >>> job = client.originate('9196@vm-host:5080',
        dp_exten=9197,
        proxy='intermediary_hostname:5060
    )
    >>> result = job.get(timeout=30)  # block up to 30 seconds waiting for result
    '4d9b4128-bd0f-11e4-9d26-74d02bc595d7'  # the originated session uuid

    >>> job.sess_uuid   # a special attr which is always reserved for originate results
    '4d9b4128-bd0f-11e4-9d26-74d02bc595d7'

    >>> client.hupall()  # hangup the call


Call control using Switchy apps
-------------------------------
To use Switchy at its fullest potential, :doc:`applications <apps>` can be
written to process state tracked by the `EventListener`. The main
benefit is that apps can be written in pure Python somewhat like the
`mod_python <https://freeswitch.org/confluence/display/FREESWITCH/mod_python>`_
module provided with *FreeSWITCH*. Switchy gives the added benefit that
the Python process does not have to run on the slave machine and in fact
**multiple** applications can be managed independently of **multiple** slave
configurations thanks to Switchy's use of the :ref:`ESL inbound method <inbound>`.


.. _appload:

App Loading
***********
Switchy apps are loaded using :py:meth:`switchy.observe.Client.load_app`.
Each app is associated with a `uuid` if none is provided which allows for
the appropriate callback lookups to be completed by the `EventListener`.

We can now accomplish the same tone play steps from above using the
built-in :py:class:`~switchy.apps.players.TonePlay` app::

    >>> from switchy.apps.players import TonePlay
    >>> client.load_app(TonePlay)
    Feb 25 13:27:43 [INFO] switchy.Client@vm-host observe.py:1020 : Loading call app 'TonePlay'
    'fd27be58-bd1b-11e4-b22d-74d02bc595d7'  # the app uuid since None provided

    >>> client.apps.TonePlay
    <sangoma.switchy.apps.players.TonePlay at 0x7f7c5fdaf650>

    >>> isinstance(client.apps.TonePlay, TonePlay)  # Loading the app type instantiates it
    True

.. note::
    App loading is *atomic* so if you mess up app implementation you don't have
    to worry that inserted callbacks are left registered with the `EventListener`

Assuming the Switchy :ref:`park-only dialplan <parkonly>` is used by the
*external* sip profile we can now originate our call again::

    >>> job = client.originate('park@vm-host:5080',
        app_name='park',  # not the Switchy `app` see `build_originate_cmd`
        proxy='intermediary_hostname:5060',
        app_id=client.apps.TonePlay.cid
    )
    >>> job.wait(10)  # wait for call to connect
    >>> call = client.listener.calls[job.sess_uuid]  # look up the call by originating sess uuid
    >>> call.hangup()

Example Snippet
---------------
As a summary, here is an snippet showing all these steps tied together:

.. code-block:: python

    import time
    from switchy import Client, EventListener
    from switchy.apps import TonePlay

    # init
    listener = EventListener('vm-host')
    client = Client('vm-host', listener=listener)
    client.connect()
    listener.connect()
    listener.start()

    # app load
    id = client.load_app(TonePlay)
    # call
    job = client.originate(
        'park@vm-host',
        proxy='intermediary_hostname',
        app_id=id
    )
    sessid = job.get(30)
    assert sessid == job.sess_uuid
    # hangup
    call = client.listener.calls[job.sess_uuid]
    orig_sess = call.sessions[0]  # get the originating session
    time.sleep(10)  # why not
    orig_sess.hangup()
