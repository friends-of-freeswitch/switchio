# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Common testing call flows
"""
import inspect
from collections import OrderedDict, namedtuple
from .. import utils
from ..apps import app
from ..marks import event_callback


@app
class TonePlay(object):
    """Play a 'milli-watt' tone on the outbound leg and echo it back
    on the inbound
    """
    @event_callback('CHANNEL_PARK')
    def on_park(self, sess):
        if sess.is_inbound():
            sess.answer()

    @event_callback("CHANNEL_ANSWER")
    def on_answer(self, sess):
        # inbound leg simply echos back the tone
        if sess.is_inbound():
            sess.echo()

        # play infinite tones on calling leg
        if sess.is_outbound():
            sess.playback('tone_stream://%(251,0,1004)',
                          params={'loops': '-1'})


RecInfo = namedtuple("RecInfo", "host caller callee")


@app
class PlayRec(object):
    '''Play a recording to the callee and record it onto the local file system

    This app can be used in tandem with MOS scoring to verify audio quality.
    The filename provided must exist in the FreeSWITCH sounds directory such
    that ${FS_CONFIG_ROOT}/${sound_prefix}/<category>/<filename> points to a
    valid wave file.
    '''
    timer = utils.Timer()

    def prepost(
        self,
        client,
        filename='ivr-founder_of_freesource.wav',
        category='ivr',
        clip_length=4.25,  # measured empirically for the clip above
        sample_rate=8000,
        iterations=1,  # number of times the speech clip will be played
        callback=None,
        rec_period=5.0,  # in seconds (i.e. 1 recording per period)
        rec_stereo=False,
    ):
        self.filename = filename
        self.category = category
        self.framerate = sample_rate
        self.clip_length = clip_length
        if callback:
            assert inspect.isfunction(callback), 'callback must be a function'
            assert len(inspect.getargspec(callback)[0]) == 1
        self.callback = callback
        self.rec_period = rec_period
        self.stereo = rec_stereo
        self.log = utils.get_logger(self.__class__.__name__)
        self.silence = 'silence_stream://-1'  # infinite silence stream
        self.iterations = iterations
        self.tail = 1.0

        # slave specific
        soundsdir = client.cmd('global_getvar sounds_dir')
        self.soundsprefix = client.cmd('global_getvar sound_prefix')
        # older FS versions don't return the deep path
        if soundsdir == self.soundsprefix:
            self.soundsprefix = '/'.join((self.soundsprefix, 'en/us/callie'))

        self.recsdir = client.cmd('global_getvar recordings_dir')
        self.audiofile = '{}/{}/{}/{}'.format(
            self.soundsprefix, self.category, self.framerate, self.filename)
        self.call2recs = OrderedDict()
        self.host = client.host

        # self.stats = OrderedDict()

    def __setduration__(self, value):
        """Called when an originator changes it's `duration` attribute
        """
        if value == float('inf'):
            self.iterations, self.tail = value, 1.0
        else:
            self.iterations, self.tail = divmod(value, self.clip_length)
        if self.tail < 1.0:
            self.tail = 1.0

    @event_callback("CHANNEL_PARK")
    def on_park(self, sess):
        if sess.is_inbound():
            sess.answer()

    @event_callback("CHANNEL_ANSWER")
    def on_answer(self, sess):
        call = sess.call
        if sess.is_inbound():
            # rec the callee stream
            elapsed = self.timer.elapsed()
            if elapsed >= self.rec_period:
                filename = '{}/callee_{}.wav'.format(self.recsdir, sess.uuid)
                sess.start_record(filename, stereo=self.stereo)
                self.call2recs.setdefault(call.uuid, {})['callee'] = filename
                call.vars['record'] = True
                # mark all rec calls to NOT be hung up automatically
                # (see the `Originator`'s bj callback)
                call.vars['noautohangup'] = True
                self.timer.reset()

            # set call length
            call.vars['iterations'] = self.iterations
            call.vars['tail'] = self.tail

        if sess.is_outbound():
            if call.vars.get('record'):  # call is already recording
                # rec the caller stream
                filename = '{}/caller_{}.wav'.format(self.recsdir, sess.uuid)
                sess.start_record(filename, stereo=self.stereo)
                self.call2recs.setdefault(call.uuid, {})['caller'] = filename
            else:
                self.trigger_playback(sess)

        # always enable a jitter buffer
        # sess.broadcast('jitterbuffer::60')

    @event_callback("PLAYBACK_START")
    def on_play(self, sess):
        fp = sess['Playback-File-Path']
        self.log.debug("Playing file '{}' for session '{}'"
                       .format(fp, sess.uuid))

        self.log.debug("fp is '{}'".format(fp))
        if fp == self.audiofile:
            sess.vars['clip'] = 'signal'
        elif fp == self.silence:
            # if playing silence tell the peer to start playing a signal
            sess.vars['clip'] = 'silence'
            peer = sess.call.get_peer(sess)
            if peer:  # may have already been hungup
                peer.breakmedia()
                peer.playback(self.audiofile)

    @event_callback("PLAYBACK_STOP")
    def on_stop(self, sess):
        '''On stop either trigger a new playing of the signal if more
        iterations are required or hangup the call.
        If the current call is being recorded schedule the recordings to stop
        and expect downstream callbacks to schedule call teardown.
        '''
        self.log.debug("Finished playing '{}' for session '{}'".format(
                      sess['Playback-File-Path'], sess.uuid))
        if sess.vars['clip'] == 'signal':
            vars = sess.call.vars
            vars['playback_count'] += 1

            if vars['playback_count'] < vars['iterations']:
                sess.playback(self.silence)
            else:
                # no more clips are expected to play
                if vars.get('record'):  # stop recording both ends
                    tail = vars['tail']
                    sess.stop_record(delay=tail)
                    peer = sess.call.get_peer(sess)
                    if peer:  # may have already been hungup
                        # infinite silence must be manually killed
                        peer.breakmedia()
                        peer.stop_record(delay=tail)
                else:
                    # hangup calls not being recorded immediately
                    self.log.debug("sending hangup for session '{}'"
                                   .format(sess.uuid))
                    if not sess.hungup:
                        sess.sched_hangup(0.5)  # delay hangup slightly

    def trigger_playback(self, sess):
        '''Trigger clip playback on the given session by doing the following:
        - Start playing a silence stream on the peer session
        - This will in turn trigger a speech playback on this session in the
        "PLAYBACK_START" callback
        '''
        peer = sess.call.get_peer(sess)
        peer.playback(self.silence)  # play infinite silence
        peer.vars['clip'] = 'silence'
        # start counting number of clips played
        sess.call.vars['playback_count'] = 0

    @event_callback("RECORD_START")
    def on_rec(self, sess):
        self.log.debug("Recording file '{}' for session '{}'".format(
            sess['Record-File-Path'], sess.uuid)
        )
        # mark this session as "currently recording"
        sess.vars['recorded'] = False
        # sess.setvar('timer_name', 'soft')

        # start signal playback on the caller
        if sess.is_outbound():
            self.trigger_playback(sess)

    @event_callback("RECORD_STOP")
    def on_recstop(self, sess):
        self.log.debug("Finished recording file '{}' for session '{}'".format(
            sess['Record-File-Path'], sess.uuid))
        # mark as recorded so user can block with `EventListener.waitfor`
        sess.vars['recorded'] = True
        if sess.hungup:
            self.log.warn(
                "sess '{}' was already hungup prior to recording completion?"
                .format(sess.uuid))

        # if sess.call.vars.get('record'):
        #     self.stats[sess.uuid] = sess.con.api(
        #         'json {{"command": "mediaStats", "data": {{"uuid": "{0}"}}}}'
        #         .format(sess.uuid)
        #     ).getBody()

        # if the far end has finished recording then hangup the call
        if sess.call.get_peer(sess).vars.get('recorded', True):
            self.log.debug("sending hangup for session '{}'".format(sess.uuid))
            if not sess.hungup:
                sess.sched_hangup(0.5)  # delay hangup slightly
            recs = self.call2recs[sess.call.uuid]

            # invoke callback for each recording
            if self.callback:
                self.callback(
                    RecInfo(self.host, recs['caller'], recs['callee'])
                )


@app
class MutedPlayRec(PlayRec):

    def trigger_playback(self, sess):
        '''
        1) Mute the peer session
        2) Trigger endless clip playback on both sessions
        '''
        peer = sess.call.get_peer(sess)
        # mute seems racey so do it twice
        peer.mute()
        peer.mute()
        # start counting number of clips played
        sess.call.vars['playback_count'] = 0
        sess.vars['playback_count'] = 0
        peer.vars['playback_count'] = 0
        # stash mute states
        sess.call.vars['muted'] = peer
        sess.call.vars['unmuted'] = sess
        # start endless playback
        sess.playback(self.audiofile, endless=True)
        peer.playback(self.audiofile, endless=True)

    @event_callback("PLAYBACK_START")
    def on_play(self, sess):
        fp = sess['Playback-File-Path']
        self.log.debug("Playing file '{}' for session '{}'"
                       .format(fp, sess.uuid))

        self.log.debug("fp is '{}'".format(fp))
        muted = sess is sess.call.vars['muted']
        self.log.debug(
            "session '{}' is {}muted"
            .format(sess.uuid, '' if muted else 'un')
        )

    @event_callback("PLAYBACK_STOP")
    def on_stop(self, sess):
        '''On stop either swap the mute state of the channels if more
        iterations are required or hangup the call.
        If the current call is being recorded schedule the recordings to stop
        and expect downstream callbacks to schedule call teardown.
        '''
        self.log.debug("Finished playing '{}' for session '{}'".format(
                      sess['Playback-File-Path'], sess.uuid))

        sess.vars['playback_count'] += 1
        vars = sess.call.vars
        # on the first session to finish playing back (i.e. once per playback)
        # do a mute swap
        if sess.vars['playback_count'] > vars['playback_count']:
            vars['playback_count'] += 1
            # swap mute states
            last_muted = vars['muted']
            vars['unmuted'].mute()
            vars['muted'] = vars['unmuted']
            vars['unmuted'] = last_muted

            if vars['playback_count'] < vars['iterations']:
                last_muted.unmute()
            else:  # no more clips are expected to play
                if vars.get('record'):
                    # stop recording both ends
                    self.log.debug("stopping recording for session '{}'"
                                   .format(sess.uuid))
                    sess.record('stop', 'all')
                    # sess.breakmedia()  # triggers a bug in FS slave...
                    peer = sess.call.get_peer(sess)
                    if peer:  # may have already been hungup
                        # infinite silence must be manually killed
                        peer.record('stop', 'all')
                        # peer.breakmedia()  # triggers a bug in FS slave...
                else:
                    # hangup calls not being recorded immediately
                    self.log.debug("sending hangup for session '{}'"
                                   .format(sess.uuid))
                    if not sess.hungup:
                        sess.sched_hangup(0.5)  # delay hangup slightly
