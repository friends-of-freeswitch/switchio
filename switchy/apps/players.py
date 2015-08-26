# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Common testing call flows
"""
import inspect
from collections import OrderedDict, namedtuple
from ..apps import app
from ..marks import event_callback
from ..utils import get_logger

@app
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


RecInfo = namedtuple("RecInfo", "host caller callee")

@app
class PlayRec(object):
    '''Play a recording to the callee and record it onto the local file system

    This app can be used in tandem with MOS scoring to verify audio quality.
    The filename provided must exist in the FreeSWITCH sounds directory such
    that ${FS_CONFIG_ROOT}/${sound_prefix}/<category>/<filename> points to a
    valid wave file.
    '''
    def __init__(
        self,
        filename='ivr-founder_of_freesource.wav',
        category='ivr',
        rate=8000,
        iterations=1,  # number of times the speech clip will be played
        callback=None,
        rec_rate=1,  # in calls/recording (i.e. 10 is 1 recording per 10 calls)
        rec_stereo=False,
    ):
        self.filename = filename
        self.category = category
        self.rate = rate
        if callback:
            assert inspect.isfunction(callback), 'callback must be a function'
            assert len(inspect.getargspec(callback)[0]) == 1
        self.callback = callback
        self.rec_rate = rec_rate
        self.stereo = rec_stereo
        self.log = get_logger(self.__class__.__name__)
        self.silence = 'silence_stream://0'  # infinite silence stream
        self.iterations = iterations
        self.call_count = 0

    def prepost(self, client):
        self.soundsdir = client.cmd('global_getvar sound_prefix')
        self.recsdir = client.cmd('global_getvar recordings_dir')
        self.audiofile = '{}/{}/{}/{}'.format(
            self.soundsdir, self.category, self.rate, self.filename)
        self.call2recs = OrderedDict()
        self.host = client.host

    @event_callback("CHANNEL_PARK")
    def on_park(self, sess):
        if sess.is_inbound():
            sess.answer()

    @event_callback("CHANNEL_ANSWER")
    def on_answer(self, sess):
        if sess.is_inbound():
            self.call_count += 1
            # rec the callee stream
            if not (self.call_count % self.rec_rate):
                filename = '{}/callee_{}.wav'.format(self.recsdir, sess.uuid)
                sess.start_record(filename, stereo=self.stereo)
                self.call2recs.setdefault(sess.call.uuid, {})['callee'] = filename
                sess.call.vars['record'] = True
                self.call_count = 0

        if sess.is_outbound():
            if sess.call.vars.get('record'):
                # rec the caller stream
                filename = '{}/caller_{}.wav'.format(self.recsdir, sess.uuid)
                sess.start_record(filename, stereo=self.stereo)
                self.call2recs.setdefault(sess.call.uuid, {})['caller'] = filename
            else:
                self.trigger_playback(sess)

    @event_callback("PLAYBACK_START")
    def on_play(self, sess):
        fp = sess['Playback-File-Path']
        self.log.info("Playing file '{}' for session '{}'"
                      .format(fp, sess.uuid))

        self.log.debug("fp is '{}'".format(fp))
        if fp == self.audiofile:
            sess.vars['clip'] = 'signal'
        elif fp == self.silence:
            # if playing silence tell the peer to start playing a signal
            sess.vars['clip'] = 'silence'
            peer = sess.call.get_peer(sess)
            peer.breakapp()
            peer.playback(self.audiofile)

    @event_callback("PLAYBACK_STOP")
    def on_stop(self, sess):
        '''Hangup up the session once playback completes
        '''
        self.log.info("Finished playing '{}' for session '{}'".format(
                      sess['Playback-File-Path'], sess.uuid))
        if sess.vars['clip'] == 'signal':
            vars = sess.call.vars
            vars['playback_count'] += 1

            if vars['playback_count'] < self.iterations:
                sess.playback(self.silence)
            else:
                if sess.call.vars.get('record'):
                    # stop recording both ends
                    sess.stop_record(delay=2)
                    # kill the peer's app
                    peer = sess.call.get_peer(sess)
                    peer.breakapp()
                    peer.stop_record(delay=2)
                else:
                    # hangup calls not being recorded immediately
                    self.log.info("sending hangup for session '{}'"
                                  .format(sess.uuid))
                    sess.sched_hangup(0.5)  # delay hangup slightly

    def trigger_playback(self, sess):
        '''Trigger clip playback on the given session by doing the following:
        1) Start playing a silence stream on the peer session
        2) This will in turn trigger a speech playback on this session in
           the "PLAYBACK_START" callback
        '''
        peer = sess.call.get_peer(sess)
        peer.playback(self.silence)  # play infinite silence
        peer.vars['clip'] = 'silence'
        # start counting number of clips played
        sess.call.vars['playback_count'] = 0

    @event_callback("RECORD_START")
    def on_rec(self, sess):
        self.log.info("Recording file '{}' for session '{}'".format(
            sess['Record-File-Path'], sess.uuid))
        # mark this session as "currently recording"
        sess.vars['recorded'] = False
        sess.setvar('timer_name', 'soft')

        # start playback from the caller side
        if sess.is_outbound():
            self.trigger_playback(sess)

    @event_callback("RECORD_STOP")
    def on_recstop(self, sess):
        self.log.info("Finished recording file '{}' for session '{}'".format(
            sess['Record-File-Path'], sess.uuid))
        # mark as recorded so user can block with `EventListener.waitfor`
        sess.vars['recorded'] = True
        if sess.hungup:
            self.log.warn(
                "sess '{}' was already hungup prior to recording completion?"
                .format(sess.uuid))
        # if the far end has finished recording then hangup the call
        if sess.call.get_peer(sess).vars.get('recorded', True):
            self.log.info("sending hangup for session '{}'".format(sess.uuid))
            sess.sched_hangup(0.5)  # delay hangup slightly
            recs = self.call2recs[sess.call.uuid]
            if self.callback:
                self.callback(RecInfo(self.host, recs['caller'], recs['callee']))
