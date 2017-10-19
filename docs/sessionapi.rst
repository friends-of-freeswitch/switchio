.. toctree::
    :maxdepth: 2
    :hidden:

    api
    apps

Session API
===========
*switchio* wraps *FreeSWITCH*'s `event header fields`_ and `call management commands`_
inside the :py:class:`switchio.models.Session` type.

There is already slew of supported commands and we encourage you to
add any more you might require via a pull request on `github`_.

Accessing *FreeSWITCH* variables
--------------------------------
Every ``Session`` instance has access to all it's latest received *event
headers* via standard python ``__getitem__`` access:

.. code-block:: python

    sess['Caller-Direction']

All chronological event data is kept until a ``Session`` is destroyed.
If you'd like to access older state you can use the underlying
:py:class:`~switchio.models.Events` instance:

.. code-block:: python

    # access the first value of my_var
    sess.events[-1]['variable_my_var']

Note that there are some distinctions to be made between different types
of `variable access`_ and in particular it would seem that
*FreeSWITCH*'s event headers follow the `info app names`_:

.. code-block:: python

    # standard headers require no prefix
    sess['FreeSWITCH-IPv6']
    sess['Channel-State']
    sess['Unique-ID']

    # channel variables require a 'variable_' prefix
    sess['variable_sip_req_uri']
    sess['variable_sip_contact_user']
    sess['variable_read_codec']
    sess['sip_h_X-switchio_app']


.. _event header fields:
    https://freeswitch.org/confluence/display/FREESWITCH/Event+List
.. _call management commands:
    https://freeswitch.org/confluence/display/FREESWITCH/mod_commands#mod_commands-CallManagementCommands
.. _github:
    https://github.com/sangoma/switchio
.. _variable access:
    https://freeswitch.org/confluence/display/FREESWITCH/XML+Dialplan#XMLDialplan-AccessingVariables
.. _info app names:
    https://freeswitch.org/confluence/display/FREESWITCH/Channel+Variables#ChannelVariables-InfoApplicationVariableNames(variable_xxxx)
