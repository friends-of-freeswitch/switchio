# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Marks for annotating callback functions
"""
from functools import partial


def marker(event_type, cb_type='callback'):
    """Decorator to mark a callback function
    for handling events of a particular type
    """
    et_attr = '_switchio_event'
    cbt_attr = '_switchio_cb_type'

    def inner(callback):
        try:
            getattr(callback, et_attr).append(event_type)
        except AttributeError:
            setattr(callback, et_attr, [event_type])
        setattr(callback, cbt_attr, cb_type)
        return callback
    return inner


event_callback = marker
handler = partial(marker, cb_type='handler')


def has_callbacks(ns):
    """Check if this namespace contains switchio callbacks

    :param ns namespace: the namespace object containing marked callbacks
    :rtype: bool
    """
    return any(getattr(obj, '_switchio_event', False) for obj in
               vars(ns).values())


def get_callbacks(ns, skip=(), only=False):
    """Deliver all switchio callbacks found in a namespace object yielding
    event `handler` marked functions first followed by `event_callbacks`.

    :param ns namespace: the namespace object containing marked callbacks
    :yields: event_type, callback_type, callback_obj
    """
    callbacks = []
    for name in (name for name in dir(ns) if name not in skip):
        try:
            obj = object.__getattribute__(ns, name)
        except AttributeError:
            continue
        try:
            ev_types = getattr(obj, '_switchio_event', False)
            cb_type = getattr(obj, '_switchio_cb_type', None)
        except ReferenceError:  # handle weakrefs
            continue

        if ev_types:  # only marked attrs
            if not only or cb_type == only:
                for ev in ev_types:
                    if cb_type == 'handler':  # deliver handlers immediately
                        yield ev, cb_type, obj
                    else:
                        callbacks.append((ev, cb_type, obj))
    else:  # yield all callbacks last
        for tup in callbacks:
            yield tup
