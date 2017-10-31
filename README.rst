switchio
========
asyncio_ powered FreeSWITCH_ cluster control using pure Python_ 3.5+!

|pypi| |travis| |versions| |pypi_downloads| |docs|

``switchio`` (pronounced *Switch Ee OoH*) is the next evolution of `switchy`_
(think *Bulbasaur* -> *Ivysaur*) which leverages modern Python's new native
coroutine_ syntax and, for now, asyncio_.

API-wise the project intends to be the *flask_ for VoIP* but with
a focus on performance and scalability more along the lines of sanic_.

Please `read the docs`_ for more information!

.. _asyncio: https://docs.python.org/3.6/library/asyncio.html
.. _FreeSWITCH: https://freeswitch.org/
.. _Python: https://www.python.org/
.. _switchy: https://www.python.org/
.. _coroutine: https://docs.python.org/3.6/library/asyncio-task.html
.. _flask: http://flask.pocoo.org/
.. _sanic: https://github.com/channelcat/sanic
.. _read the docs: https://switchio.readthedocs.org/


Installation
============
For Python 3.5+ ``switchio`` comes ready out of the box::

    pip install switchio

Dependencies
============
Nothing other then Python 3.5+ is required!

If you'd like to record performance measurements some optional numerical
packages can be used:

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
    :target: https://pypi.org/project/switchio
.. |pypi| image:: https://img.shields.io/pypi/v/switchio.svg
    :target: https://pypi.org/project/switchio
.. |travis| image:: https://img.shields.io/travis/friends-of-freeswitch/switchio/master.svg
    :target: https://travis-ci.org/friends-of-freeswitch/switchio
.. |pypi_downloads| image:: https://img.shields.io/pypi/d/switchio.svg
    :target: https://pypi.org/project/switchio
.. |docs| image:: https://readthedocs.org/projects/switchio/badge/?version=latest
    :target: http://switchio.readthedocs.io
