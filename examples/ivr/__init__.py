"""
Example IVR

This package contains the following modules which contain example code for
developing a very simple IVR using switchy and FreeSWITCH:

call_logic.py:

- A switchy event processing app which defines the basic event
  processing logic required to process DTMF inputs, play back prompt-files
  and take call recordings.

- An example decorator implementation for registering DTMF sequence
  processing callbacks very similar to `flask` routes
  (http://flask.pocoo.org/docs/0.10/quickstart/#routing).

dialer.py:

- An example auto-dialer using the built-in `switchy.app.call_gen.Originator`
  with basic support for multi-campaign batch dialling.

WARNING:
    This code should by no means be considered production ready. It is
    meant to serve as an overly documented example of how to begin implementing
    an IVR application.

NOTES:
    - you can configure the arguments to `main` in dailer.py to adjust
      campaign settings and FreeSWITCH IP information.
"""
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
from dialer import main

if __name__ == '__main__':
    # invoke the auto-dialer
    main()
