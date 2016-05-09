Running Unit Tests
==================
Switchy's unit test set relies on `pytest`_ and can be run easily by simply
providing a *FreeSWITCH* slave hostname which has been :doc:`deployed <fsconfig>` with the
baseline config.

To run simply invoke pytest from the source dir with one extra param::

    py.test --fshost='fs_slave_hostname' tests/

`SIPp`_ and `pysipp`_ are required to be installed locally in order to run call/load tests.

To run multi-slave tests at least two slave hostnames are required::

    py.test --fsslaves='["fs_slave_hostname1","fs_slave_hostname2"]' tests/


.. hyperlinks
.. _pytest:
    http://pytest.org
.. _SIPp:
    https://github.com/SIPp/sipp
.. _pysipp:
    https://github.com/SIPp/pysipp
