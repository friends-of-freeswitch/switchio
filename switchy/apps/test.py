# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Common testing call flows
"""
from collections import OrderedDict
from ..marks import event_callback
from ..utils import get_logger


class TonePlay(object):
    """Play a 'milli-watt' tone on the outbound leg and echo it back
    on the inbound
    """
    @event_callback('CHANNEL_PARK')
    def on_park(self, sess):
        if sess.is_inbound():
            sess.answer()

        # play infinite tones on calling leg
        if sess.is_outbound():
            sess.broadcast('playback::{loops=-1}tone_stream://%(251,0,1004)')

    @event_callback("CHANNEL_ANSWER")
    def on_answer(self, sess):
        # inbound leg simply echos back the tone
        if sess.is_inbound():
            sess.broadcast('echo::')


class PlayRec(object):
    '''Play a recording to the callee where it will be recorded
    onto the local file system. This app can be used in tandem with
    MOS scoring to verify audio quality.
    '''
    def prepost(self, client):
        self.soundsdir = client.cmd('global_getvar sound_prefix')
        self.recsdir = client.cmd('global_getvar recordings_dir')
        self.log = get_logger(self.__class__.__name__)
        self.audiofile = '{}/ivr/8000/ivr-founder_of_freesource.wav'.format(
            self.soundsdir)
        self.call2recs = OrderedDict()

    @event_callback("CHANNEL_PARK")
    def on_park(self, sess):
        if sess.is_outbound():
            # rec the tx stream
            filename = '{}/tx_{}.wav'.format(self.recsdir, sess.uuid)
            sess.start_record(filename)
            self.call2recs.setdefault(sess.call.uuid, {})['tx'] = filename
            sess.playback(self.audiofile)

        # inbound leg simply echos back the stream
        if sess.is_inbound():
            sess.answer()

    @event_callback("CHANNEL_ANSWER")
    def on_answer(self, sess):
        if sess.is_inbound():
            # rec the rx stream
            filename = '{}/rx_{}.wav'.format(self.recsdir, sess.uuid)
            sess.start_record(filename)
            self.call2recs.setdefault(sess.call.uuid, {})['rx'] = filename

    @event_callback("PLAYBACK_START")
    def on_play(self, sess):
        self.log.info("Playing file '{}' for session '{}'".format(
                      self.audiofile, sess.uuid))

    @event_callback("PLAYBACK_STOP")
    def on_stop(self, sess):
        '''Hangup up the session once playback completes
        '''
        self.log.info("Finished playing file '{}' for session ".format(
                      self.audiofile, sess.uuid))
        callee = sess.call.sessions[-1]
        callee.stop_record(delay=2)

    @event_callback("RECORD_START")
    def on_rec(self, sess):
        self.log.info("Recording file '{}' for session '{}'".format(
            sess['Record-File-Path'], sess.uuid))
        sess.vars['recorded'] = False

    @event_callback("RECORD_STOP")
    def on_recstop(self, sess):
        self.log.info("Finished recording file '{}' for session '{}'".format(
            sess['Record-File-Path'], sess.uuid))
        # mark as recorded so user can block with `EventListener.waitfor`
        sess.vars['recorded'] = True
        sess.sched_hangup(0.5)  # delay hangup slightly
