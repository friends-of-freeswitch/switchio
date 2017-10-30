# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Marks for annotating callback functions
"""
from functools import partial


def extend_attr_list(obj, attr, items):
    try:
        getattr(obj, attr).extend(items)
        # current_items.extend(items)
    except AttributeError:
        setattr(obj, attr, list(items))


def marker(event_type, cb_type='callback', subscribe=()):
    """Decorator to mark a callback function
    for handling events of a particular type
    """
    et_attr = 'switchio_init_events'
    es_attr = 'switchio_events_sub'
    cbt_attr = '_switchio_handler_type'

    def inner(handler):
        extend_attr_list(handler, et_attr, [event_type])
        # append any additional subscriptions
        extend_attr_list(handler, es_attr, subscribe)
        setattr(handler, cbt_attr, cb_type)
        return handler

    return inner


callback = event_callback = marker
coroutine = partial(marker, cb_type='coroutine')
handler = partial(marker, cb_type='handler')


def has_callbacks(ns):
    """Check if this namespace contains switchio callbacks.

    :param ns namespace: the namespace object containing marked callbacks
    :rtype: bool
    """
    return any(getattr(obj, 'switchio_init_events', False) for obj in
               vars(ns).values())


def get_callbacks(ns, skip=(), only=False):
    """Deliver all switchio callbacks found in a namespace object yielding
    event `handler` marked functions first followed by non-handlers such as
    callbacks and coroutines.

    :param ns namespace: the namespace object containing marked handlers
    :yields: event_type, callback_type, callback_obj
    """
    non_handlers = []
    for name in (name for name in dir(ns) if name not in skip):
        try:
            obj = object.__getattribute__(ns, name)
        except AttributeError:
            continue
        try:
            ev_types = getattr(obj, 'switchio_init_events', False)
            cb_type = getattr(obj, '_switchio_handler_type', None)
        except ReferenceError:  # handle weakrefs
            continue

        if ev_types:  # only marked attrs
            if not only or cb_type == only:
                for ev in ev_types:
                    if cb_type == 'handler':  # deliver handlers immediately
                        yield ev, cb_type, obj
                    else:
                        non_handlers.append((ev, cb_type, obj))
    else:  # yield all non_handlers last
        for tup in non_handlers:
            yield tup
