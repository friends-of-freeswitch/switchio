.. toctree::
    :maxdepth: 2
    :hidden:

    api


Call Applications
=================
*switchio* supports writing and composing call control *applications* written in
pure Python. An *app* is simply a `namespace`_ which defines **a set of event
callbacks** [#]_.

Apps are somewhat analogous to `extensions`_ in *FreeSWITCH*'s
`XML dialplan`_ interface and can similarly be activated using any
`event header`_ *or* `channel variable`_ value of your choosing.
Callbacks are invoked based on the recieved `event type`_.


*Apps* can be implemented each as a standalone Python `namespace`_ which can
hold state and be mutated at runtime. This allows for all sorts of dynamic call
processing logic. *Apps* can also be shared across a *FreeSWITCH* process cluster
allowing for centralized call processing overtop a scalable service system.

Applications are :ref:`loaded <appload>` either using a :py:class:`~switchio.api.Client`
or, in the case of an *switchio* cluster :doc:`Service <services>`, an
:py:class:`~switchio.apps.AppManager` instance.

API
---
Apps are usually implemented as plain old Python `classes`_ which contain
methods decorated using the :py:mod:`switchio.marks` module.

Currently the marks supported would be one of::

    @event_callback("EVENT_NAME")
    @handler("EVENT_NAME")

Where `EVENT_NAME` is any of the strings supported by the ESL `event type`_
list.

Additionally, app types can support a :py:func:`prepost` callable which serves
as a setup/teardown fixture mechanism for the app to do pre/post app loading
execution. It can be either of a function or generator.

.. note::
    For examples using :py:func:`prepost` see the extensive set of built-in
    apps under :py:mod:`switchio.apps`.


Event Callbacks
***************
``event_callbacks`` are methods which typically receive a type from
:py:mod:`switchio.models` as their first (and only) argument. This
type is most often a :py:class:`~switchio.models.Session`.

.. note::
    Technically the method will receive whatever is returned as the 2nd
    value from the preceeding event `handler` looked up in the event
    processing loop, but this is an implementation detail and may change
    in the future.

Here is a simple callback which counts the number of answered sessions in
a global::

    import switchio

    num_calls = 0

    @switchio.event_callback('CHANNEL_ANSWER')
    def counter(session):
        global num_calls
        num_calls += 1

.. note::
    This is meant to be a simple example and not actually
    implemented for practical use.
    :py:meth:`switchio.handlers.EventListener.count_calls` exists
    for this very purpose.


Event Handlers
**************
An event handler is any callable marked by :py:meth:`handler` which
is expected to handle a received `ESLEvent` object and process it within the
:py:class:`~switchio.handlers.EventListener` event loop. It's function signature
should expect a single argument, that being the received event.

Example handlers can be found in the :py:class:`~switchio.handlers.EventListener`
such as the default `CHANNEL_ANSWER` handler

.. literalinclude:: ../switchio/handlers.py
    :pyobject: EventListener._handle_answer

As you can see a knowledge of the underlying `ESL SWIG python
package`_ usually is required for `handler` implementations.


Examples
--------
.. _toneplayapp:

TonePlay
********
As a first example here is the :py:class:`~switchio.apps.players.TonePlay`
app which is provided as a built-in for ``switchio``

.. literalinclude:: ../switchio/apps/players.py
    :pyobject: TonePlay


:py:class:`Clients <switchio.api.Client>` who load this app will originate
calls wherein a simple tone is played infinitely and echoed back to
the caller until each call is hung up.

.. _proxyapp:

Proxier
*******
An example of the :ref:`proxy dialplan <proxydp>` can be
implemented quite trivially::

    import switchio

    class Proxier(object):
        @switchio.event_callback('CHANNEL_PARK')
        def on_park(self, sess):
            if sess.is_inbound():
                sess.bridge(dest_url="${sip_req_user}@${sip_req_host}:${sip_req_port}")

.. _cdrapp:

CDR
***
The measurement application used by the
:py:class:`~switchio.apps.call_gen.Originator` to gather stress testing
performance metrics from call detail records:

.. literalinclude:: ../switchio/apps/measure/cdr.py
    :pyobject: CDR

It simply inserts the call record data on hangup once for each *call*.

PlayRec
*******
This more involved application demonstrates *FreeSWITCH*'s ability to play
and record rtp streams locally which can be used in tandem with MOS to do
audio quality checking:

.. literalinclude:: ../switchio/apps/players.py
    :pyobject: PlayRec

For further examples check out the :py:mod:`~switchio.apps`
sub-package which also includes the very notorious
:py:class:`switchio.apps.call_gen.Originator`.

.. [#] Although this may change in the future with the introduction of native
       `asyncio`_ coroutines in Python 3.5.

.. hyperlinks
.. _extensions:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-Extensions
.. _channel variable:
    https://freeswitch.org/confluence/display/FREESWITCH/Channel+Variables
.. _event header:
    https://freeswitch.org/confluence/display/FREESWITCH/Event+List#EventList-Eventfields
.. _event type:
    https://freeswitch.org/confluence/display/FREESWITCH/Event+List
.. _XML dialplan:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan
.. _namespace:
    https://docs.python.org/3/tutorial/classes.html#python-scopes-and-namespaces
.. _ESL:
    https://freeswitch.org/confluence/display/FREESWITCH/Event+Socket+Library
.. _classes:
    https://docs.python.org/3/tutorial/classes.html#a-first-look-at-classes
.. _ESL SWIG python package:
    https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL
.. _asyncio:
    https://docs.python.org/3/library/asyncio.html
