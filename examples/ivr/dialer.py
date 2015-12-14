# IVR Dialer
#
# Author: Nenad Corbic <ncorbic@sangoma.com>
#
# IVR Dialer demonstrates how to launch one or more outbound campaigns using
# FreeSWITCH or Sangoma NetBorder Appliance.
# IVR Dialer peformsn the following
#   1. Connect to Sangoma NetBorder VoIP Gateway
#   2. Load user defined IVRCallControl application that
#      will be in charge of the each connected call.
#   3. Accept user camapign configuration
#      Number of calls to dial, what did to user per call
#      Number of calls per sec
#   4. Call IVRCallControl applicatoin per call.
#
# All user logic should be defined in IVRCallLogic Class!
# The IVRCallLogic is defined in ivr_call_logic.py example.
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
from switchy import get_originator
from ivr_call_logic import IVRCallLogic

# Enable logging to stderr
# Debug levels: 'INFO' for production, 'DEBUG' for development
log = switchy.utils.log_to_stderr('INFO')

# Specify FreeSWITCH or Sangoma NSG IP information
# In this example the sample app is running on
# Sangoma NSG appliance hence the use of local address
host = "127.0.0.1"
host = "10.10.26.33"
port = 8821

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
       NOTE: Developer is suppose to supply their own DID from a list or DB
    """
    # if statement is just an easy way to switch between one or the other
    if True:
        # Make a FreeTDM SS7/PRI Call
        # Adding F at the end of the DID disables remote SS7 overlap dialing
        # which can add 5 sec to the incoming call setup time.
        return {
            'dest_url': 'a/4113F',
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
