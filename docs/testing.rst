Running Unit Tests
==================
``switchio``'s unit test set relies on `pytest`_  and `tox`_.  Tests require a
*FreeSWITCH* slave process which has been :doc:`deployed <fsconfig>`
with the required baseline config and can be accessed by hostname.

To run all tests invoke `tox` from the source dir and pass the FS hostname::

    tox -- --fshost=hostname.fs.com

`SIPp`_ and `pysipp`_ are required to be installed locally in order to run call/load tests.

To run multi-slave tests at least two slave hostnames are required::

    tox -- --fsslaves=fs.slave.hostname1,fs.slave.hostname2


.. hyperlinks
.. _pytest:
    http://pytest.org
.. _tox:
    http://tox.readthedocs.io
.. _SIPp:
    https://github.com/SIPp/sipp
.. _pysipp:
    https://github.com/SIPp/pysipp
