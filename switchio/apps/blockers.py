# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Simulate different types of blocking behaviour such as might be seen by a high
frequency auto-dialler.
"""
from functools import partial
from ..models import Session
from ..marks import callback
from ..utils import get_logger
from ..apps import app


@app
class CalleeBlockOnInvite(object):
    """Reject all inbound INVITES immediately

    If `response` is not specified respond with with 480 Temporarily
    Unavailable, else, use the provided response.
    """
    def prepost(self, response='NORMAL_CLEARING'):
        self._response = None
        self.action = None
        self.response = response

    @property
    def response(self):
        return self._response

    @response.setter
    def response(self, value):
        if isinstance(value, int):
            self.action = partial(Session.respond, response=value)
        else:  # str case
            self.action = partial(Session.hangup, cause=value)

    @callback("CHANNEL_CREATE")
    def on_invite(self, sess):
        if sess.is_inbound():
            self.action(sess)


@app
class CalleeRingback(object):
    """Simulate calls which reach early media but never connect.

    `ringback` determines the argument to `Session.playback` which is by
    default: 'tone_stream://%(2000, 4000, 440, 480)' i.e. US tones.

    `ring_response` determines the provisionary response
    ( eg. for SIP 'pre_answer' -> 183 , 'ring_ready' -> 180 ).

    `calle[er]_hup_after` determines the time in seconds before a hangup is
    triggered by either of the caller/callee respectively.
    """
    def prepost(
        self,
        ringback='tone_stream://%(2000, 4000, 440, 480)',
        callee_hup_after=float('inf'),
        caller_hup_after=float('inf'),
        ring_response='pre_answer',  # or could be 'ring_ready' for 180
        auto_duration=False,
    ):
        self.ringback = ringback
        self.callee_hup_after = callee_hup_after
        self.auto_duration = auto_duration,
        self.caller_hup_after = caller_hup_after
        self.ring_response = ring_response
        self.log = get_logger(self.__class__.__name__)

    def __setduration__(self, value):
        if self.auto_duration:
            self.callee_hup_after = value

    @callback("CHANNEL_CALLSTATE")
    def on_cs(self, sess):
        self.log.debug("'{}' sess CS is '{}'".format(
            sess['Call-Direction'], sess['Channel-Call-State']))

        if sess['Channel-Call-State'] == 'RINGING':
            if sess.is_inbound():
                # send ring response
                sess.broadcast("{}::".format(self.ring_response))

                # playback US ring tones
                if self.ringback:
                    sess.playback(self.ringback)

                # hangup after a delay
                if self.callee_hup_after < float('inf'):
                    sess.sched_hangup(self.callee_hup_after - sess.uptime)

            # hangup caller after a delay
            if sess.is_outbound() and self.caller_hup_after < float('inf'):
                    sess.sched_hangup(self.caller_hup_after)
