switchio
=======
async FreeSWITCH_ cluster control using pure Python_!

|pypi| |travis| |versions| |pypi_downloads| |docs|

``switchio`` intends to be the "flask_ for VoIP" but with a focus on performance and
scalable service system design. Please `read the docs`_ for more information!

.. _FreeSWITCH: https://freeswitch.org/
.. _Python: https://www.python.org/
.. _flask: http://flask.pocoo.org/
.. _read the docs: https://switchio.readthedocs.org/

Installation
============
Note that you need to at least have the SWIG_ package installed in your
Linux distribution before installing ``switchio`` via ``pip``::

    yum install swig
    # or
    apt-get install swig

Once you have SWIG installed (the ``swig`` command should be available)
you can use ``pip`` to install ``switchio``::

    pip install switchio

.. _SWIG: http://www.swig.org/

Dependencies
============
Currently `switchio` uses the `ESL SWIG package`_ distributed with the FreeSWITCH sources.
We intend to add alternative backends in the future including greenswitch_ and support
for mod_amqp_.

.. _ESL SWIG package: https://freeswitch.org/confluence/display/FREESWITCH/Python+ESL
.. _greenswitch: https://github.com/EvoluxBR/greenswitch
.. _mod_amqp: https://freeswitch.org/confluence/display/FREESWITCH/mod_amqp

Some optional numerical packages are required to record performance measurements:

===============  ================ ================================
Feature          Dependency        Installation
===============  ================ ================================
Metrics Capture  `pandas`_        ``pip install switchio[metrics]``
Graphing         `matplotlib`_    ``pip install switchio[graphing]``
HDF5             `pytables`_ [#]_ ``pip install switchio[hdf5]``
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

.. |versions| image:: https://img.shields.io/pypi/pyversions/switchio.svg
    :target: https://pypi.python.org/pypi/switchio
.. |pypi| image:: https://img.shields.io/pypi/v/switchio.svg
    :target: https://pypi.python.org/pypi/switchio
.. |travis| image:: https://img.shields.io/travis/friends-of-freeswitch/switchio/master.svg
    :target: https://travis-ci.org/friends-of-freeswitch/switchio
.. |pypi_downloads| image:: https://img.shields.io/pypi/d/switchio.svg
    :target: https://pypi.python.org/pypi/switchio
.. |docs| image:: https://readthedocs.org/projects/switchio/badge/?version=latest
    :target: http://switchio.readthedocs.io/en/latest/?badge=latest
