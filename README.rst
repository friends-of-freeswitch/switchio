Switchy
=======
A FreeSWITCH_ control library and stress testing tool

.. _FreeSWITCH: https://freeswitch.org/

Features
========
Among other things, Switchy let's you

- drive multiple FreeSWITCH processes as a call generator cluster
- write call control applications (IVRs, auto-dialers, ...) in pure
  Python using a thin ESL api wrapper
- record and display performance metrics captured during stress tests
- avoid monolithic Python dependencies like :code:`twisted`

Installation
============

Dependencies
------------
Currently, Switchy relies on the `ESL SWIG package`_ distributed with the
FreeSWITCH sources. Luckily, Sangoma has nicely `packaged this with setuptools`_
so manual installation is not necessary.

.. _ESL SWIG package: https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL
.. _packaged this with setuptools: https://github.com/sangoma/python-ESL

Some optional numerical packages are required to record
performance measurements. See the :code:`setup.py`'s
:code:`extras_require` for details.

Using pip
---------
At the moment :code:`switchy` is still pre major release software and we recommend
cloning and installing directly from this repo:

::

    git clone git://github.com/sangoma/switchy.git
    pip install -r switchy/requirements.txt switchy/

Documentation
=============
Full usage documentation can be found on readthedocs_

.. _readthedocs: https://switchy.readthedocs.org/

License
=======
All files that are part of this project are covered by the following
license, except where explicitly noted.

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.
