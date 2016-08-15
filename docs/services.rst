.. _services:
.. toctree::
    :maxdepth: 2
    :hidden:

    api
    apps


Building a cluster service
==========================
`switchy` supports building full fledged routing systems just like you can
with *FreeSWITCH*'s `XML dialplan`_ but with the added benefit that you
can use a centralized "dialplan" to control a *FreeSWITCH* process cluster.

This means call control logic can reside in one (or more) *switchy* process(es)
running on a separate server allowing you to separate the *brains* and
*logic* from the *muscle* and *functionality* when designing a scalable
*FreeSWITCH* service system.


A service is very easy to create given a set of :ref:`deployed <fsconfig>`
*Freeswitch* processes:

.. code-block:: python

    from switchy import Service, event_callback

    class Proxier(object):
        """Proxy all inbound calls to the destination specified in the SIP
        Request-URI.
        """
        @event_callback('CHANNEL_PARK')
        def on_park(self, sess):
            if sess.is_inbound():
                sess.bridge(dest_url="${sip_req_uri}")

    s = Service(['FS_host1.com', 'FS_host2.com', 'FS_host3.com'])
    s.apps.load_app(Proxier, app_id='default')
    s.run()  # blocks forever

In this example all three of our *FreeSWITCH* servers load a `Proxier`
:doc:`app <apps>` which simply bridges calls to the destination requested in
the SIP Request-URI header. The `app_id='default'` kwarg is required to tell
the internal event loop that this app should be used as the default (i.e. when
no other app has consumed the event/session for processing).

.. _flask-like:

`Flask`-like routing
--------------------
Using the :py:class:`~switchy.apps.routers.Router` :doc:`app <apps>` we
can define a routing system reminiscent of `flask`_.

Let's start with an example of `blocking certain codes`_:

.. code-block:: python

    from switchy.apps.routers import Router

    router = Router(guards={
        'Call-Direction': 'inbound',
        'variable_sofia_profile': 'external'})

    @router.route('00(.*)|011(.*)', response='407')
    def reject_international(sess, match, router, response):
        sess.respond(response)
        sess.hangup()


There's a few things going on here:

- A :py:class:`~switchy.apps.routers.Router` is created with a *guard*
  ``dict`` which determines strict constraints on *event headers* which
  **must** be matched exactly for the ``Router`` to invoke registered
  (via ``@route``) functions.
- We decorate a function, ``reject_international``, which registers it to be
  invoked whenever an international number is dialed and will block such numbers
  with a SIP ``407`` response code.
- The first 3 arguments to ``reject_international`` are required,
  namely, ``sess``, ``match``, and ``router`` and correspond to the
  :py:class:`~switchy.models.Session`, `re.MatchObject`_, and
  :py:class:`~switchy.apps.routers.Router` respectively.


In summmary, we can define *patterns* which must be matched against
`event headers`_ before a particular *route function* will be invoked.

The signature for ``Router.route`` which comes from
:py:class:`~switchy.utils.PatternCaller` is:

.. py:decorator:: route(pattern, field=None, kwargs)

and works by taking in a `regex` ``pattern``, an optional ``field`` (default
is ``'Caller-Destination-Number'``) and ``kwargs``.
The ``pattern`` must be matched against the ``field`` *event header* in order for
the *route* to be called with ``kwargs`` (i.e. ``reject_international(**kwargs)``).

Let's extend our example to include some routes which `bridge`_ differently
based on the default ``'Caller-Destination-Number'`` *event header*:

.. code-block:: python

    from switchy.apps.routers import Router

    router = Router({'Call-Direction': 'inbound'})

    @router.route('00(.*)|011(.*)', response='407')
    @router.route('1(.*)', gateway='long_distance_trunk')
    @router.route('2[1-9]{3}$', out_profile='internal', proxy='salespbx.com')
    @router.route('4[1-9]{3}$', out_profile='internal', proxy='supportpbx.com')
    def bridge2dest(sess, match, router, out_profile=None, gateway=None,
                    proxy=None, response=None):
        if response:
            sess.log.warn("Rejecting international call to {}".format(
                sess['Caller-Destination-Number']))
            sess.respond(response)
            sess.hangup()

        sess.bridge(
            # bridge back out the same profile if not specified
            # (the default action taken by bridge)
            profile=out_profile,
            gateway=gateway,
            # always use the SIP Request-URI
            dest_url=sess['variable_sip_req_uri'],
            proxy=proxy,
        )

Which defines that:

- all international calls will be blocked.
- any *inbound* calls prefixed with ``1`` will be `bridged` to our long distance provider.
- all ``2xxx`` dialed numbers will be directed to the sales PBX.
- all ``4xxx`` dialed numbers will be directed to the support PBX.

Notice that we can *parameterize* the inputs to the routing function
using `kwargs`_. This lets you specify data inputs you'd like used when
a particular field matches. If not provided, sensible defaults can be
specified in the function signature.

Also note that the idea of `transferring to a context`_ becomes a simple function call:

.. code-block:: python

    @router.route("^(XXXxxxxxxx)$")
    def test_did(sess, match, router):
        # call our route function from above
        return bridge2dest(sess, match, router, profile='external')

Just as before, we can run our ``router`` as a service and use a
single "dialplan" for all nodes in our *FreeSWITCH* cluster:

.. code-block:: python

    s = Service(['FS_host1.com', 'FS_host2.com', 'FS_host3.com'])
    s.apps.load_app(router, app_id='default')
    s.run()  # blocks forever


.. note::
    If you'd like to try out *switchy* routes alongside your existing
    XML dialplan (assuming you've added the :ref:`park only <parkonly>`
    context in your existing config) you can either pass in
    ``{"Caller-Context": "switchy"}`` as a ``guard`` or you can load
    the router with:

    ``s.apps.load_app(router, app_id='switchy', header='Caller-Context')``


Replicating XML dialplan features
*********************************
The main difference with using *switchy* for call control is that
everything is processed at **runtime** as opposed to having separate *parse*
and *execute* phases.

Retrieving Variables
^^^^^^^^^^^^^^^^^^^^
`Accessing variable`_ values from *FreeSWITCH* is already built into
*switchy*'s :doc:`sessionapi` using traditional `getitem`_ access.

Basic Logic
^^^^^^^^^^^
As a first note, you can accomplish any "logical" *field* pattern match
either directly in Python or by the *regex* expression to ``Router.route``:

Here is the equivalent of the logical `AND`_ example:

.. code-block:: python

    from datetime import datetime

    @router.route('^500$')
    def on_sunday(sess, match, router, profile='internal', did='500'):
        """On Sunday no one works in support...
        """
        did = '531' if datetime.today().weekday() == 6 else did
        sess.bridge('{}@example.com'.format(did), profile=profile)

And the same for logical `OR`_ example:

.. code-block:: python

    import re

    # by regex
    @router.route('^500$|^502$')
    def either_ext(sess, match, router):
        sess.answer()
        sess.playback('ivr/ivr-welcome_to_freeswitch.wav')

    # by if statement
    @router.route('^.*$')
    def match(sess, match, router):
        if re.match("^Michael\s*S?\s*Collins", sess['variable_caller_id_name']) or\
                re.match("^1001|3757|2816$", sess['variable_caller_id_number']):
            sess.playback("ivr/ivr-dude_you_rock.wav")
        else:
            sess.playback("ivr/ivr-dude_you_suck.wav")


Nesting logic
^^^^^^^^^^^^^
`Nested conditions`_ Can be easily accomplished using plain old `if statements`_:

.. code-block:: python

    @router.route('^1.*(\d)$')
    def play_wavfile(sess, match, router):
        # get the last digit
        last_digit = match.groups()[0]

        # only play the extra file when last digit is '3'
        if last_digit == '3':
            sess.playback('foo.wav')

        # always played if the first digit is '1'
        sess.playback('bar.wav')


Break on true
^^^^^^^^^^^^^
Halting route execution (known as `break on true`_) can be done currently by returning
``True`` from your routing function:

.. code-block:: python

    @router.route('^1.*(\d)$')
    def play_wavfile(sess, match, router):
        if not sess['Caller-Destination-Number'] == "1100":
            return True  # stop all further routing


Record a random sampling of call center agents
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Here's an example of randomly recording call-center agents who block
their outbound CID:

.. code-block:: python

    import random

    @router.route('^\*67(\d+)$')
    def block_cid(sess, match, router):
        did = match.groups()[0]

        if sess.is_outbound():
            # mask CID
            sess.broadcast('privacy::full')
            sess.setvars({'privacy': 'yes', 'sip_h_Privacy': 'id'})

            if random.randint(1, 6) == 4:
                sess.log.debug("recording a sneaky agent to /tmp/agents/")
                sess.start_record('/tmp/agents/{}_to_{}.wav'.format(sess.uuid, did))

.. _XML dialplan:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan
.. _nested conditions:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-NestedConditions
.. _flask:
    http://flask.pocoo.org/docs/0.11/quickstart/#routing
.. _re.MatchObject:
    https://docs.python.org/3/library/re.html#match-objects
.. _event headers:
    https://freeswitch.org/confluence/display/FREESWITCH/Event+List
.. _if statements:
    https://docs.python.org/3/tutorial/controlflow.html#if-statements
.. _AND:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-Example2:LogicalAND
.. _OR:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-Example3:LogicalOR
.. _variable access:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-AccessingVariables
.. _blocking certain codes:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-Example16:Blockcertaincodes
.. _break on true:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-break="on-true"
.. _kwargs:
    https://docs.python.org/3/tutorial/controlflow.html#keyword-arguments
.. _transferring to a context:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-Example9:RoutingDIDtoanextension
.. _bridge:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_dptools%3A+bridge
.. _accessing variable:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-AccessingVariables
.. _getitem:
    https://docs.python.org/3/reference/datamodel.html#object.__getitem__
