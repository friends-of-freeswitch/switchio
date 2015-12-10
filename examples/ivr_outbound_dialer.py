# Switchy IVR Outbound Dialer
#
# Author: Nenad Corbic <ncorbic@sangoma.com>
#
# This application is designed to demonstrate Switchy capabilities
# and ease of use.  The application will connect to actively running
# FreeSWITCH or Sangoma NSG application. It will then originate
# a single call and play introductory IVR message. From then
# on application will wait for user input via DTMF.
#
# IVR Menu
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

import time
import switchy
import threading
from switchy.marks import event_callback
from switchy import get_originator

# Enable logging to stderr
# Debug levels: 'INFO' for production, 'DEBUG' for development
log = switchy.utils.log_to_stderr('INFO')

# Specify FreeSWITCH or Sangoma NSG IP information
# In this example the sample app is running on
# Sangoma NSG appliance hence the use of local address
host = "127.0.0.1"
port = 8821


class IVRCallLogic(object):
    """
    IVR Call Logic switchy app.
    All custom development should be done on this class.

    You can use the following variable types:
        self.<var_name> instance variables are global in nature.
        call.vars.['<var_name>'] should be used for per call info and state.
    """
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

        # Stop the dtmf timeout timer if one exists
        self.cancel_dtmf_timer(sess)

        # IVR Menu - a map of digits to actions
        actions = {
            '911': 'ivr-contact_system_administrator.wav',
            '811': 'ivr-hello.wav',
            '111': 'hangup',
        }

        digits = call.vars.get('incoming_dtmf', [])
        if len(digits) == 3:
            digits_str = ''.join(digits)
            log.info("'{}': Matched on dtmf sequence '{}'"
                     .format(sess.uuid, digits_str))
            log.info("'{}': Playing file STARTED".format(sess.uuid))

            # lookup IVR action (eg. this can be a call to an external
            # database / extension list)
            action = actions.get(digits_str)

            # process action
            if action is 'hangup':
                log.info("'{}': User chose to hangup".format(sess.uuid))
                sess.hangup()
            elif action:
                play_filename = "{}/{}".format(self.sound_dir, action)
                call.vars['playing'] = True
                sess.playback(play_filename)
            else:
                log.warn(
                    "No action could be found at extension '{}'"
                    .format(digits_str)
                )

        # End of IVR menu: If max digits where entered reset the dtmf queue
        if len(digits) >= 3:
            log.debug("'{}': Resetting DTMF queue".format(sess.uuid))
            call.vars['incoming_dtmf'] = []  # reset dtmf digits list

        # User has not triggered the menu. Restart the DTMF timeout
        if call.vars['playing'] is not True:
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


# Make an outbound call
# This function will be called by originator for each call
# User is supposed to provide the outbound DID or SIP URL for each call
#
# SIP Call:
#   dest_url='did@domain.com' Remote SIP URI
#   dest_profile='internal'   NSG defined SIP profile name
#   dest_endpoint='sofia'     For SIP calls one MUST set sofia
#
# FreeTDM Call:
#   dest_url='[A,a]/did'      A=ascending hunt, a=descending hunt, DID number
#   dest_profile='g1'         profile is used as trunk group definition
#                             (eg. g1 == group 1)
#   endpoint='freetdm"        For TDM calls on MUST set freetdm
#
# In this example we are making a FreeTDM Call.
# Change True to False in order to make SIP calls.
def create_url():
    """Replacement field callback
    """
    # if statement is just an easy way to switch between one or the other
    if True:
        # Make a FreeTDM SS7/PRI Call
        # Adding F at the end of the DID disables remote SS7 overlap dialing
        # which can add 5 sec to the incoming call setup time.
        # NOTE: Developer is suppose to supply their own DID from a list or DB
        return {
            'dest_url': 'a/1000F',
            'dest_profile': 'g1',
            'dest_endpoint': 'freetdm'
        }
    else:
        # Make a SIP Call
        return {
            'dest_url': '1000@10.10.12.5:6060',
            'dest_profile': 'internal',
            'dest_endpoint': 'sofia'
        }


# Create an 'originator' which is an auto-dialer.
# You can tell it how many calls to make and at what frequency.
# After the first batch of calls are complete, you can choose to start dialing
# again. There are 3 configurable variables:
# - max_calls_per_campaign
# - max_call_attempts_per_sec
# - max_campaigns
#
# In this example the dialer will make 1 outbound call on first campaign.
# By increasing the max_campaigns variable, the dialer will repeat as many dial
# campaigns.
max_calls_per_campaign = 1
max_call_attempts_per_sec = 1
max_campaigns = 1

# create an auto-dialer
originator = get_originator(
    [(host, port)],
    apps=(IVRCallLogic,),
    auto_duration=False,
    rep_fields_func=create_url
)

# Initialize dial variables in order for switchy to trigger create_url()
# function above.
# The create_url function is a callback which has the task of specifying the
# dial information per call (i.e. it is called once for each call).
originator.pool.evals(
    ("""client.set_orig_cmd(
     dest_url='{dest_url}',
     profile='{dest_profile}',
     endpoint='{dest_endpoint}',
     app_name='park')""")
)


# Setup calls per sec
originator.rate = max_call_attempts_per_sec

# Setup maximum number of calls to make
# max erlangs / simultaneous calls
originator.limit = max_calls_per_campaign

# Maximum number of calls to dial out
originator.max_offered = max_calls_per_campaign

# Start the initial campaign - Originator will start making outbound calls
originator.start()

# Keeps a count of campaigns
campaign_cnt = 0

# Here is an example of how to keep an eye on the campaign.
# After the campaign is over, check to see if another campaign should start
while (True):
    if originator.stopped() and originator.count_calls() == 0:

        log.info(originator)  # log state info and current load

        # Check to see if we should run another camapign
        campaign_cnt += 1
        if campaign_cnt >= max_campaigns:
            break

        log.info("Starting new campaign\n")

        # We must increase the max allowed calls in order
        # for dialer to initiate another max_calls_per_campaign
        originator.max_offered += max_calls_per_campaign
        originator.start()

    time.sleep(1)

log.info("All campaigns done: stopping...\n")
originator.shutdown()
