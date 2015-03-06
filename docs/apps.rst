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
:py:class:`class` which can hold state as well as be mutated at runtime.

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
    argument from the preceeding event `handler` looked up in the event
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
    implemented for practical use. The :py:class:`switchy.observer.EventListener`
    implements a counter method :py:meth:`count_calls` for this very purpose.


Event Handlers
**************
An event handler is any callable marked by :py:meth:`handler` which
is expected to handle a received `ESLEvent` object and process it within the
:py:class:`~switchy.observe.EventListener` event loop. It's function signature
should expect a single argument being the received event.

Example handlers can be found in the :py:class:`~switchy.observe.EventListener`
such as the default `CHANNEL_ORIGINATE` handler::

    @handler('CHANNEL_ORIGINATE')
    def _handle_originate(self, e):
        '''Handle originate events
        '''
        uuid = e.getHeader('Unique-ID')
        sess = self.sessions.get(uuid, None)
        self.log.debug("handling originated session '{}'".format(uuid))
        if sess:
            sess.update(e)
            # store local time stamp for originate
            sess.originate_time = time.time()
            self.total_originated_sessions += 1
            return True, sess
        return False, sess

As you can see a knowledge of the underlying :ref:`ESL SWIG python
package` usually is required for `handler` implementations.


Example applications
--------------------
TonePlay
********
As a first example here is the `TonePlay` app which is provided as a built-in
for Switchy::

    from switchy import event_callback

    class TonePlay(object):
        """Play a tone on the outbound leg and echo it back
        on the inbound
        """
        @event_callback('CHANNEL_PARK')
        def answer_inbound(self, sess):
            if sess.is_inbound():
                sess.answer()

        @event_callback("CHANNEL_ANSWER")
        def tone_play(self, sess):
            # play infinite tones on calling leg
            if sess.is_outbound():
                sess.broadcast('playback::{loops=-1}tone_stream://%(251,0,1004)')

            # inbound leg simply echos back the tone
            if sess.is_inbound():
                sess.broadcast('echo::')

:py:class:`Clients` who load this app will originate calls wherein
a simple tone is played infinitely and echoed back to the caller
until each call is hung up.

.. _proxyapp:

Proxier
*******
An example implementation of the :ref:`proxy dialplan <proxydp>` can be
implemented quite trivially::

    import switchy

    class Proxier(object):
        @switchy.event_callback('CHANNEL_PARK')
        def on_park(self, sess):
            if sess.is_inbound():
                sess.bridge(dest_url="${sip_req_user}@${sip_req_host}:${sip_req_port}")

For further more complex examples check out the :py:mod:`switchy.apps`
sub-package with the most complicated app being the notorious `Originator`.
