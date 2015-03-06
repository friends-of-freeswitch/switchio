Switchy
=======
A fast FreeSWITCH ESL control library with an emphasis on load testing.

Among other things, Switchy let's you

    - drive N slaves as call generators
    - write call control applications in pure python using a
      super thin ESL api wrapper
    - collect performance metrics using numpy
    - dynamically modify call flows at runtime

Installation
============

Dependencies
------------
Switchy relies on the ESL SWIG package distributed with the FreeSWITCH
sources. Manual installation instructions for the ESL package can be
found here: https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL

Using pip
---------
The simplest way to install this package is using pip with the command:

    pip install git+git://github.com/sangoma/switchy.git

Documentation
=============
Full usage documentation can be found at readthedocs:
https://switchy.readthedocs.org/

License
=======
All files that are part of this project are covered by the following
license, except where explicitly noted.

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.
