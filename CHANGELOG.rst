Change Log
==========
All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog`_ and this project adheres to
`Semantic Versioning`_.

.. _Keep a Changelog: http://keepachangelog.com/en
.. _Semantic Versioning: http://semver.org/


0.1.0.alpha0 - 2017-10-27
-------------------------
Added
*****
``switchio`` is a hard fork of Sangoma's `switchy`_ project which seeks
to leverage features in modern Python (3.5+) including the language's
new native `coroutine` syntax and supporting event loop backend(s) such
as the standard library's `asyncio`_. The change history prior to
this fork can be found in the original projects's log. Python 2.7
support will be dropped likely for the first non-alpha release.

- Full (self-contained) CI using a production FreeSWITCH ``docker`` image
  and runs on ``TravisCI``.
- ESL inbound protocol implementation written in pure Python using an
  ``asyncio.Protocol``.
- Event loop core rewritten to support Python 3.5 coroutines and `asyncio`_
  engine.
- Coroutine app support using a ``@coroutine`` decorator and an extended
  ``Session`` API which allows for awaiting particular (sets) of events.

Removed
*******
- Legacy IVR example(s)

.. _switchy: https://github.com/sangoma/switchy
.. _asyncio: https://docs.python.org/3.6/library/asyncio.html
.. _coroutine: https://docs.python.org/3.6/library/asyncio-task.html
