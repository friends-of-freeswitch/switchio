# IVR Call Logic Application
#
# Author: Nenad Corbic <ncorbic@sangoma.com>
#
# IVR Call Logic application is designed to demonstrate Switchy IVR
# capabilities.  The IVR logic is structured as its own class/file.
# This way developer can concentrate on building ther IVR application
# separate from the dialer.
#
# This application will be imported by the IVR Dialer, and dialer
# will call the IVRCallLogic for every connected outbound call.
#
# Exampele IVR Menu
#  911 - Play file contact system admin
#  811 - Play file hello
#  111 - Cause a hangup
#  If user times out on DTMF a hello playback will be heard
#
# All user logic should be defined in IVRCallLogic Class.
#
# Variables
#  self.<variables>       are global in nature.
#  call.vars.['var_name'] should be used for per call info and state
#
# Switchy Documentation
#  https://github.com/sangoma/switchy/blob/master/switchy/models.py
#          class: Session Event Call Job
#
#  https://github.com/sangoma/switchy/blob/master/switchy/observe.py
#          class: EventListener Client
#
# Sample Switchy Applications
#  https://switchy.readthedocs.org/en/latest/apps.html
#
# License:
#  BSD License
#  http://opensource.org/licenses/bsd-license.php
#
#  Copyright (c) 2015, Sangoma Technologies Inc
#  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#  1. Developer makes use of Sangoma NetBorder Gateway or Sangoma Session
#     Border Controller
#  2. Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#  3. Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
#  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
#  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
#  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
#  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
#  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.

import switchy
import threading
import re
from functools import partial
from collections import OrderedDict
from switchy.marks import event_callback

# Enable logging to stderr
# Debug levels: 'INFO' for production, 'DEBUG' for development
log = switchy.utils.log_to_stderr('INFO')


# IVR DID pattern matching and callback registration similar to
# `flask.route` (http://flask.pocoo.org/docs/0.10/quickstart/#routing)
class PatternCaller(object):
    """A `flask`-like pattern to callback registrar and invoker.

    Allows for registering callback functions via decorator syntax which
    should be called when `PatterCaller.call_matches` is invoked with a
    matching value.
    """
    def __init__(self):
        self.regex2funcs = OrderedDict()

    def __call__(self, pattern, **kwargs):
        """Decorator interface allowing you to register callback functions
        with a regex pattern and kwargs. When `lookup` is called with a value,
        any callable registered with a matching regex pattern will be invoked
        with the provided kwargs.
        """
        def inner(func):
            self.regex2funcs.setdefault(pattern, []).append(
                partial(func, **kwargs))
            return func

        return inner

    def call_matches(self, value, **kwargs):
        """Perform linear lookup and callback invocation for all functions
        registered with a matching pattern. Each function is invoked with the
        matched value as its first argument and any arguments provided here.
        Any kwargs which were provided at registration are also forwarded.
        """
        consumed = False
        for patt, funcs in self.regex2funcs.iteritems():
            match = re.match(patt, value)
            if match:
                consumed = True
                for func in funcs:
                        func(match=match, **kwargs)
        return consumed


class IVRCallLogic(object):
    """
    IVR Call Logic switchy app.
    All custom development should be done on this class.

    You can use the following variable types:
        self.<var_name> instance variables are global in nature.
        call.vars.['<var_name>'] should be used for per call info and state.
    """
    # Use a singleton across all instances of this class such that pattern
    # matching and callbacks can be shared over a clustered app.
    route = PatternCaller()

    def prepost(self, client, listener):
        """Defines a fixture-like pre/post app load hook for performing
        provisioning steps before this app is loaded.
        """
        # Get the install directory of FreeSWITCH or Sangoma NSG and append
        # recording to it. By default, on Sangoma systems, FreeSWITCH resides
        # in /usr/local/freeswitch, NSG resides in /usr/local/nsg.
        self.base_dir = client.cmd('global_getvar base_dir')
        self.recdir = "{}/{}".format(self.base_dir, "recording")
        log.info("Setting recording dir to '{}".format(self.recdir))

        # Get the install directory of NSG and append sounds to it
        self.sound_dir = "{}/{}".format(
            self.base_dir, 'sounds/en/us/callie/ivr/8000')
        log.info("Setting sounds dir to '{}".format(self.sound_dir))

        self.stereo = False  # toggle whether to make stereo recordings

        self.dtmf_menu_max_digits = 3

        # mod_sndfile module is a must in order to play prompts
        # Example of how to execute FreeSWITCH/NSG commands as from the CLI
        try:
            client.cmd('load mod_sndfile')
        except switchy.utils.CommandError:
            pass

    @event_callback('CHANNEL_PARK')
    def on_park(self, sess):
        """Answer all inbound sessions immediately
        """
        if sess.is_inbound():
            sess.answer()  # answer the inbound session

    @event_callback("CHANNEL_ANSWER")
    def on_answer(self, sess):
        # reference to the 'call' object which may contain multiple
        # sessions if the call is routed back to the originating
        # FreeSWITCH server.
        call = sess.call

        # This application does not deal with inbound calls.
        if sess.is_inbound():
            log.info(
                "'{}': received ANSWER for inbound session".format(sess.uuid))

        # Outbound call has just been answered
        # Developer would start the introductory IVR message
        if sess.is_outbound():

            # Start recording a call
            call.vars['record'] = True
            sess.start_record(
                '{}/callee_{}.wav'.format(self.recdir, sess.uuid),
                stereo=self.stereo
            )

            # Play IVR initial greeting
            call.vars['play_welcome'] = True
            play_filename = '{}/ivr-welcome.wav'.format(self.sound_dir)
            sess.playback(play_filename)

            # create a list for storing received dtmf digits
            call.vars['incoming_dtmf'] = []

            # At this point we wait for the PLAYBACK_STOP event to
            # arrive and then start a timeout trigger as in DTMF handler

    @staticmethod
    def cancel_dtmf_timer(sess):
        timer = sess.vars.get('dtmf_timer')
        if timer:
            log.debug("'{}': Cancel dtmf timeout job".format(sess.uuid))
            timer.cancel()  # if timer in 'initial' state this is a noop
        return timer

    def start_dtmf_timer(self, sess, timeout=3):
        """Start a timer thread which will invoke the dtmf timeout handler after
        `timeout` seconds. The default interval is 3 seconds.
        """
        timer = self.cancel_dtmf_timer(sess)

        # allocate a new timer
        timer = threading.Timer(timeout, self.dtmf_timeout_action, [sess])
        timer.daemon = True  # thread dies with parent process
        timer.start()  # NOTE: this launches a thread per call
        sess.vars['dtmf_timer'] = timer
        return timer

    def dtmf_timeout_action(self, sess):
        """Timer handler that implements DTMF timeout
        """
        call = sess.call
        log.info("'{}': DTMF timeout".format(sess.uuid))

        if call.vars.get('playing') is True:
            call.vars['playing'] = False
            sess.breakmedia()  # stop playback

        # Reset incoming dtmf queue
        call.vars['incoming_dtmf'] = []

        # Example of playing a prompt urging the user to try again
        play_filename = '{}/ivr-hello.wav'.format(self.sound_dir)
        call.vars['playing'] = True
        sess.playback(play_filename)

        # Trigger dtmf timeout again
        self.start_dtmf_timer(sess)

    @event_callback('DTMF')
    def on_digit(self, sess):
        """Process DTMF digit events
        """
        call = sess.call
        digit = sess['DTMF-Digit']
        log.info("'{}': DTMF dtmf digit '{}'".format(sess.uuid, digit))

        # Add incoming digit into the digit queue
        call.vars.setdefault('incoming_dtmf', []).append(digit)

        # DTMF has just been detected, stop playing any files to the user
        if call.vars.get('playing') is True:
            sess.breakmedia()
            call.vars['playing'] = False

        # Stop the dtmf timeout timer if one exists
        self.cancel_dtmf_timer(sess)

        # get the digits thus far
        digits = ''.join(call.vars.get('incoming_dtmf', []))

        # Menu processing - call all matching IVR routes/extensions
        # (See below for registered extension definitions)
        consumed = self.route.call_matches(digits, app=self, sess=sess)

        # End of menu processing
        if consumed:
            # If digits were matched to an extension reset the dtmf queue.
            log.debug("'{}': Resetting DTMF queue".format(sess.uuid))
            call.vars['incoming_dtmf'] = []  # reset dtmf digits list

        else:
            # User has not triggered a menu entry so restart the DTMF timeout
            log.warn(
                "No action could be found for extension '{}'"
                .format(digits)
            )
            if len(digits) >= self.dtmf_menu_max_digits:
                log.debug("'{}': Resetting DTMF queue".format(sess.uuid))
                call.vars['incoming_dtmf'] = []  # reset dtmf digits list

            if call.vars['playing'] is not True:
                # an extension may have triggered playback
                self.start_dtmf_timer(sess)

    @event_callback("PLAYBACK_START")
    def on_playback_start(self, sess):
        call = sess.call
        fp = sess['Playback-File-Path']
        log.info("'{}': got PLAYBACK_START '{}'".format(sess.uuid, fp))
        if call.vars.get('play_welcome') is True:
            log.info("'{}': Playing Welcome STARTED".format(sess.uuid))

    @event_callback("PLAYBACK_STOP")
    def on_playback_stop(self, sess):
        call = sess.call
        fp = sess['Playback-File-Path']
        log.info("'{}': got PLAYBACK_STOP '{}'".format(sess.uuid, fp))

        # Playing is finished, set DTMF timeout
        call.vars['playing'] = False
        self.start_dtmf_timer(sess)

        if call.vars.get('play_welcome') is True:
            call.vars['play_welcome'] = False
            log.info("'{}': Playing Welcome STOPPED, Lets Wait for Digits"
                     .format(sess.uuid))

    @event_callback("RECORD_START")
    def on_record_start(self, sess):
        log.info("'{}': got RECORD_START ".format(sess.uuid))

    @event_callback("RECORD_STOP")
    def on_record_stop(self, sess):
        log.info("'{}': got RECORD_STOP ".format(sess.uuid))

    @event_callback('CHANNEL_HANGUP')
    def on_hangup(self, sess, job):
        call = sess.call
        log.info("'{}': got HANGUP ".format(sess.uuid))
        if call.vars.get('play_welcome') is True:
            call.vars['play_welcome'] = False
            log.warn("'{}': Got HANGUP while playing".format(sess.uuid))


# IVR Menu functions:
#
# Each function can match multiple DTMF sequences using regex and can be
# parameterized by the kwargs passed to the pertaining decorator.
#
@IVRCallLogic.route('811', filename='ivr-hello.wav')
@IVRCallLogic.route('911', filename='ivr-contact_system_administrator.wav')
def playback_file(match, app, sess, filename):
    """Play back a media file by according to the dialled extension.

    Note: You could also lookup an external database / extension list based
          on the `match` received here.
    """
    log.info("'{}': Matched on DTMF sequence '{}'".format(
        sess.uuid, match.group()))
    log.info("'{}': Playing file {}".format(sess.uuid, filename))
    play_filename = "{}/{}".format(app.sound_dir, filename)
    sess.call.vars['playing'] = True
    sess.playback(play_filename)


@IVRCallLogic.route('111')
def hangup_session(match, app, sess):
    """Hangup the session immediately
    """
    log.info("'{}': User chose to hangup".format(sess.uuid))
    sess.hangup()


@IVRCallLogic.route('0(.*)#', profile='internal', proxy='myproxy.com:5060')
def bridge_to_dest(match, app, sess, profile, proxy):
    """Bridge call to a remote destination.

    WARNING:
        The host/IP informations here are examples and should be replaced
        by valid destinations.
    """
    # get the digits between '9' and '#' (see the `re` module)
    extension = match.group(1)

    # bridge the call to your PBX using parsed extension
    sess.bridge(
        dest_url='{}@mypbx.com:5060'.format(extension),
        proxy=proxy,
        profile=profile,
    )
