switchy
=======
|pypi| |versions| |pypi_downloads|

FreeSWITCH_ control and stress testing using pure Python_.

| `switchy` intends to become the "flask_ for VoIP" but with a focus on performance.
| Please readthedocs_ for more information.

.. _FreeSWITCH: https://freeswitch.org/
.. _Python: https://www.python.org/
.. _flask: http://flask.pocoo.org/
.. _readthedocs: https://switchy.readthedocs.org/

Installation
============
::

    pip install switchy

Features
========

- drive a FreeSWITCH cluster as a traffic generator
- record, display and export CDR and performance metrics captured during stress tests
- write apps in pure Python to process flows from a clustered service system
- async without requiring :code:`twisted`

Dependencies
============
Currently `switchy` uses the `ESL SWIG package`_ distributed with the FreeSWITCH sources.
We intend to add alternative backends in the future including greenswitch_ and support
for mod_amqp_.

.. _ESL SWIG package: https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL
.. _greenswitch: https://github.com/EvoluxBR/greenswitch
.. _mod_amqp: https://freeswitch.org/confluence/display/FREESWITCH/mod_amqp

Some optional numerical packages are required to record performance measurements:

===============  ================ ================================
Feature          Dependency        Installation
===============  ================ ================================
Metrics Capture  `pandas`_        ``pip install switchy[metrics]``
Graphing         `matplotlib`_    ``pip install switchy[graphing]``
HDF5             `pytables`_ [#]_ ``pip install switchy[hdf5]``
===============  ================ ================================

.. [#] ``pytables`` support is a bit shaky and not recommended unless
       you intend to locally process massive data sets worth of CDRs.
       The default CSV backend is usually sufficient on a modern file
       system.

.. _pandas: http://pandas.pydata.org/
.. _matplotlib: http://matplotlib.org/
.. _pytables: http://www.pytables.org/

License
=======
All files that are part of this project are covered by the following
license, except where explicitly noted.

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.

.. |versions| image:: https://img.shields.io/pypi/pyversions/switchy.svg
    :target: https://pypi.python.org/pypi/switchy

.. |pypi| image:: https://img.shields.io/pypi/v/switchy.svg
    :target: https://pypi.python.org/pypi/switchy

.. |pypi_downloads| image:: https://img.shields.io/pypi/d/switchy.svg
    :target: https://pypi.python.org/pypi/switchy
