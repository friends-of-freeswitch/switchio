switchio
========
asyncio_ powered FreeSWITCH_ cluster control using pure Python_ 3.6+

|pypi| |github_actions| |versions| |license| |docs|

.. |versions| image:: https://img.shields.io/pypi/pyversions/switchio.svg
    :target: https://pypi.org/project/switchio
.. |pypi| image:: https://img.shields.io/pypi/v/switchio.svg
    :target: https://pypi.org/project/switchio
.. |github_actions| image:: https://github.com/friends-of-freeswitch/switchio/actions/workflows/python-app.yml/badge.svg
    :target: https://github.com/friends-of-freeswitch/switchio/actions/workflows/python-app.yml
.. |license| image:: https://img.shields.io/pypi/l/switchio.svg
    :target: https://pypi.org/project/switchio
.. |docs| image:: https://readthedocs.org/projects/switchio/badge/?version=latest
    :target: http://switchio.readthedocs.io

``switchio`` (pronounced *Switch Ee OoH*) is the next evolution of `switchy`_
(think *Bulbasaur* -> *Ivysaur*) which leverages modern Python's new native
coroutine_ syntax and, for now, asyncio_.

API-wise the project intends to be the flask_ for VoIP but with a focus on
performance and scalability more like sanic_.

.. _asyncio: https://docs.python.org/3.6/library/asyncio.html
.. _FreeSWITCH: https://freeswitch.org/
.. _Python: https://www.python.org/
.. _switchy: https://github.com/sangoma/switchy
.. _coroutine: https://docs.python.org/3.6/library/asyncio-task.html
.. _flask: http://flask.pocoo.org/
.. _sanic: https://github.com/channelcat/sanic
.. _docs: https://switchio.readthedocs.org/


Use the power of ``async`` and ``await``!
-----------------------------------------
Build a routing system using Python's new coroutine_ syntax:

.. code:: python

    from switchio.apps.routers import Router

    router = Router(
        guards={
            'Call-Direction': 'inbound',
            'variable_sofia_profile': 'external'},
        subscribe=('PLAYBACK_START', 'PLAYBACK_STOP'),
    )

    @router.route('(.*)')
    async def welcome(sess, match, router):
        """Say hello to inbound calls.
        """
        await sess.answer()  # resumes once call has been fully answered
        sess.log.info("Answered call to {}".format(match.groups(0)))

        sess.playback(  # non-blocking
            'en/us/callie/ivr/8000/ivr-founder_of_freesource.wav')
        await sess.recv("PLAYBACK_START")
        sess.log.info("Playing welcome message")

        await sess.recv("PLAYBACK_STOP")
        await sess.hangup()  # resumes once call has been fully hungup

Run this app (assuming it's in ``dialplan.py``) from the shell::

    $ switchio serve fs-host1 fs-host2 fs-host3 --app ./dialplan.py:router

You can also run it from your own script:

.. code:: python

    if __name__ == '__main__':
        from switchio import Service
        service = Service(['fs-host1', 'fs-host2', 'fs-host3'])
        service.apps.load_app(router, app_id='default')
        service.run()


Spin up an auto-dialer
----------------------
Run thousands of call flows to stress test your service system using
the built-in auto-dialer_::

    $ switchio dial fs-tester1 fs-tester2 --profile external --proxy myproxy.com --rate 100 --limit 3000

.. _auto-dialer: http://switchio.readthedocs.io/en/latest/callgen.html


Install
-------
::

    pip install switchio


Docs
----
Oh we've got them docs_!

How do I deploy my FreeSWITCH cluster?
--------------------------------------
- Enable `inbound ESL`_ connections
- Add a park-only_ dialplan (Hint: we include one here_)

See the docs_ for the deats!

.. _inbound ESL: https://freeswitch.org/confluence/display/FREESWITCH/mod_event_socket#mod_event_socket-Configuration
.. _park-only: https://freeswitch.org/confluence/display/FREESWITCH/mod_dptools%3A+park
.. _here: https://github.com/friends-of-freeswitch/switchio/blob/master/conf/switchiodp.xml


What's included?
----------------
- A slew of `built-in apps`_
- A full blown `auto-dialer`_ originally built for stress testing VoIP service systems
- Super detailed ESL event logging

.. _built-in apps: http://switchio.readthedocs.io/en/latest/apps.html
.. _auto-dialer: http://switchio.readthedocs.io/en/latest/callgen.html


How can I contribute?
---------------------
Have an idea for a general purpose ``switchio`` app or helper?
Make a PR here on GitHub!

Also, if you like ``switchio`` let us know on Riot_!

.. _Riot:  https://riot.im/app/#/room/#freeswitch:matrix.org


Wait, how is ``switchio`` different from other ESL clients?
-----------------------------------------------------------
``switchio`` differentiates itself by supporting FreeSWITCH
*process cluster control* as well as focusing on leveraging the
most modern Python language features. ``switchio`` takes pride
in being a *batteries included* framework that tries to make all
the tricky things about FreeSWITCH a cinch.


What if I'm stuck on Python 2?
------------------------------
Check out these other great projects:

- greenswitch_
- eventsocket_
- pySWITCH_
- python-ESL_

.. _greenswitch: https://github.com/EvoluxBR/greenswitch
.. _eventsocket: https://github.com/fiorix/eventsocket
.. _pySWITCH: http://pyswitch.sourceforge.net/
.. _python-ESL: https://github.com/sangoma/python-ESL


Performance monitoring
----------------------
If you'd like to record performance measurements using the
CDR_ app, some optional numerical packages can be used:

.. _CDR: http://switchio.readthedocs.io/en/latest/apps.html#cdr

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
-------
All files that are part of this project are covered by the following
license, except where explicitly noted.

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.
