.. toctree::
    :maxdepth: 2
    :hidden:

    api


Call Applications
=================
Switchy supports composing *applications* written in pure python which
roughly correspond to the actions taken by `extensions` in *FreeSWITCH*'s
xml dialplan interface. In fact, Switchy's *apps* offer extended control and
flexibility since they can be implemented as a standalone python
:py:class:`class` which can hold state and be mutated at runtime.

Applications are :ref:`loaded <appload>` using :py:class:`~switchy.observe.Client`
instances which have been associated with a respective
:py:class:`~switchy.observe.EventListener` the latter of which normally
have a one-to-one correspondence with deployed *FreeSWITCH* slave servers.


API
---
Apps are usually implemented as classes which inherit from `object` and which
contain methods decorated using the :py:mod:`switchy.marks` module

Currently the marks supported would be one of::

    @event_callback("EVENT_NAME")
    @handler("EVENT_NAME")

Where `EVENT_NAME` is any of the strings supported by the ESL event type
list as detailed `here <https://freeswitch.org/confluence/display/FREESWITCH/Event+List>`_

Additionally, app types can support a :py:func:`prepost` callable which serves
as a setup/teardown fixture mechanism for the app to do pre/post app loading
execution.


Event Callbacks
***************
`event_callbacks` are methods which typically receive a type from
:py:mod:`switchy.models` as their first (and only) argument. This
type is most often a :py:class:`~switchy.models.Session`.

.. note::
    Technically the method will receive whatever is returned as the 2nd
    value from the preceeding event `handler` looked up in the event
    processing loop, but this is an implementation detail and may change
    in the future.

Here is a simple callback which counts the number of answered sessions in
a global::

    import switchy

    num_calls = 0

    @switchy.event_callback('CHANNEL_ANSWER')
    def counter(session):
        global num_calls
        num_calls += 1

.. note::
    This is meant to be a simple example and not actually
    implemented for practical use.
    :py:meth:`switchy.observe.EventListener.count_calls` exists
    for this very purpose.


Event Handlers
**************
An event handler is any callable marked by :py:meth:`handler` which
is expected to handle a received `ESLEvent` object and process it within the
:py:class:`~switchy.observe.EventListener` event loop. It's function signature
should expect a single argument being the received event.

Example handlers can be found in the :py:class:`~switchy.observe.EventListener`
such as the default `CHANNEL_ORIGINATE` handler

.. literalinclude:: ../switchy/observe.py
    :pyobject: EventListener._handle_originate

As you can see a knowledge of the underlying :ref:`ESL SWIG python
package` usually is required for `handler` implementations.


Example applications
--------------------
.. _toneplayapp:

TonePlay
********
As a first example here is the :py:class:`~switchy.apps.players.TonePlay`
app which is provided as a built-in for Switchy

.. literalinclude:: ../switchy/apps/players.py
    :pyobject: TonePlay


:py:class:`Clients <switchy.observe.Client>` who load this app will originate
calls wherein a simple tone is played infinitely and echoed back to
the caller until each call is hung up.

.. _proxyapp:

Proxier
*******
An example of the :ref:`proxy dialplan <proxydp>` can be
implemented quite trivially::

    import switchy

    class Proxier(object):
        @switchy.event_callback('CHANNEL_PARK')
        def on_park(self, sess):
            if sess.is_inbound():
                sess.bridge(dest_url="${sip_req_user}@${sip_req_host}:${sip_req_port}")

.. _metricsapp:

Metrics
*******
The sub-application used by the
:py:class:`~switchy.apps.call_gen.Originator` to gather load
measurements:

.. literalinclude:: ../switchy/apps/measure/__init__.py
    :pyobject: Metrics

It simply inserts measurement data on hangup once for each call.

PlayRec
*******
This more involved application demonstrates *FreeSWITCH*'s ability to play
and record rtp streams locally which can be used in tandem with MOS to do
audio quality checking:

.. literalinclude:: ../switchy/apps/players.py
    :pyobject: PlayRec

For further examples check out the :py:mod:`~switchy.apps`
sub-package which also includes the very notorious
:py:class:`switchy.apps.call_gen.Originator`.
