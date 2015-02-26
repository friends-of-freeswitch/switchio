"""
Common testing call flows
"""
from ..marks import event_callback


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
