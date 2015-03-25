# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
handy utilities
"""
import sched
import inspect
import functools
import json
import types
import logging
import uuid as mod_uuid


class ESLError(Exception):
    pass


class ConfigurationError(Exception):
    pass


class CommandError(ESLError):
    pass


# fs-like log format
LOG_FORMAT = ("%(asctime)s [%(levelname)s] %(name)s %(filename)s:%(lineno)d "
              ": %(message)s")
DATE_FORMAT = '%b %d %H:%M:%S'
_log = None


def get_root_log():
    '''Get the root switchy log
    '''
    global _log
    if not _log:
        _log = logging.getLogger('switchy')
        _log.propagate = True
    return _log


def get_logger(name=None):
    '''Return a sub-log for `name` or the pkg log by default
    '''
    log = get_root_log()
    return log.getChild(name) if name else log


def log_to_stderr(level=None):
    '''Turn on logging and add a handler which prints to stderr
    '''
    log = get_root_log()
    if level:
        log.setLevel(level)
    handler = logging.StreamHandler()
    # do colours if we can
    try:
        import colorlog
        fs_colors = {
            'CRITICAL': 'bold_red',
            'ERROR': 'red',
            'WARNING': 'purple',
            'INFO': 'green',
            'DEBUG': 'yellow',
        }
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s" + LOG_FORMAT,
            datefmt=DATE_FORMAT,
            log_colors=fs_colors
        )
    except ImportError:
        logging.warning("Colour logging not supported. Please install"
                        "the colorlog module to enable")
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    handler.setFormatter(formatter)
    log.addHandler(handler)
    return log


def dirinfo(inst):
    """Return common info useful for dir output
    """
    return sorted(set(dir(type(inst)) + inst.__dict__.keys()))


def xheaderify(header_name):
    '''Prefix the given name with the freeswitch xheader token
    thus transforming it into an fs xheader variable
    '''
    return 'sip_h_X-{}'.format(header_name)


def pstr(self):
    """Pretty str repr of connection-like instances
    """
    return '{}@{}'.format(
        type(self).__name__,
        getattr(self, 'server', getattr(self, 'host', ''))
    )


def get_name(obj):
    """Return a name for object checking the usual places
    """
    try:
        return obj.__name__
    except AttributeError:
        return obj.__class__.__name__


def event2dict(event):
    '''Return event serialized data in a python dict
    Warning: this function is kinda slow!
    '''
    return json.loads(event.serialize('json').replace('\t', ''))


def uncons(first, *rest):
    """Unpack args into first element and tail as tuple
    """
    return first, rest


def compose(func_1, func_2):
    """(f1, f2) -> function
    The function returned is a composition of f1 and f2.
    """
    if not callable(func_1):
        raise TypeError("First argument to must be callable")
    if not callable(func_2):
        raise TypeError("Second argument to must be callable")

    def composition(*args, **kwargs):
        return func_1(func_2(*args, **kwargs))
    return composition


def copy_attrs(src_ns, dest, methods, props=True):
    '''Bind methods and properties on src class to dest class
    '''
    cache = {}
    for name in methods:
        attr = getattr(src_ns, name)
        if inspect.ismethod(attr):
            # WARNING: CPython specific hack - `im_func`
            setattr(dest, name, types.MethodType(attr.im_func, None, dest))
            # track get/set ifaces
            if 'get_' or 'set_' in name:
                op, sep, prop = name.rpartition('_')
                cache.setdefault(prop, []).append(op)

        elif inspect.isdatadescriptor(attr):
            attr = functools.partial(attr)
            setattr(dest.__class__, name, property(attr))

    # if there are get and set methods then optionally attach a property
    if props:
        for prop, ops in cache.items():
            if len(ops) == 2:
                setattr(dest, prop, property(
                    getattr(dest, 'get_' + prop),
                    getattr(dest, 'set_' + prop)))


def get_args(func):
    """Return the argument names found in func's signature in a tuple

    :return: the argnames, kwargnames defined by func
    :rtype: tuple
    """
    args, varargs, varkw, defaults = inspect.getargspec(func)
    index = -len(defaults) if defaults else None
    return args[slice(0, index)], args[slice(index, None if index else 0)]


def is_callback(func):
    """Check whether func is valid as a callback
    """
    return inspect.isroutine(func)


def uuid():
    """Return a new uuid1 string
    """
    return str(mod_uuid.uuid1())


class FastScheduler(sched.scheduler):

    def next_event_time_delta(self):
        """Return the time delta in seconds for the next event
        to become ready for execution
        """
        q = self.queue
        if self.empty():
            return 0
        time, priority, action, argument = q[0]
        now = self.timefunc()
        if time > now:
            return time - now
        return 0

    def fast_run(self):
        """
        Try to run events that are ready only and return immediately
        It is assumed that the callbacks will not block and the time
        is only retrieved once (when entering the function) and not
        before executing each event, so there is a chance an event
        that becomes ready while looping will not get executed
        """
        q = self.queue
        now = self.timefunc()
        while q:
            time, priority, action, argument = q[0]
            if now < time:
                return now - time
            if now >= time:
                self.cancel(q[0])
                action(*argument)
