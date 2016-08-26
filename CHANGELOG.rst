Change Log
==========
All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog`_ and this project adheres to
`Semantic Versioning`_.


.. _@vodik: https://github.com/vodik
.. _Keep a Changelog: http://flask.pocoo.org/docs/0.11/quickstart/#routing
.. _Semantic Versioning: http://flask.pocoo.org/docs/0.11/quickstart/#routing


Unreleased
----------
Added
*****
- Python 3.5 support. Thanks to `@vodik`_ for the initial work.
- Cluster service API with docs and tests
- `flask`_-like routing system with docs and tests
- Docs for the ``Session`` API
- Error checking in ``Connection.api``
- Support for the `deflect`_ dp tool

.. _deflect: https://freeswitch.org/confluence/display/FREESWITCH/mod_dptools%3A+deflect
.. _flask: http://flask.pocoo.org/docs/0.11/quickstart/#routing


0.1.0.alpha0 - 2016-08-03
-------------------------
Added
*****
Cumulatively there was **a lot** of work done on ``switchy`` as a
traffic generator for stress testing prior to this release. Most
of the initial design was with this focus using *FreeSWITCH 1.4.18*
and the SWIG python-ESL backend. The API evolved from internal tools
built around an early version of Sangoma's VoIP testing framework.

A very high level summary includes:

- A session API for invoking FreeSWITCH commands *Pythonically*
- Initial event reactor system and callback registration API
- An *apps* API for defining callback sets using decorators and
  namespaces
- A simple synchronous dialer API for VoIP functional testing
- An async auto-dialer built for stress testing using a FreeSWITCH cluster
- A cli for running simple stress tests from a console
- A slew of built-in testing apps including DTMF checking, mod_bert
  testing, conversation simulating, and *blocked call* traffic patterns.
- A CDR app and integrated measurement capture subsystem leveraging ``pandas``
- Integration and unit tests for all of the above.
