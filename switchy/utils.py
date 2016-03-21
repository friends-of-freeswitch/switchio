# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
handy utilities
"""
import sys
import time
import inspect
import functools
import json
import types
import logging
import uuid as mod_uuid
import importlib
import pkgutil


class ESLError(Exception):
    """An error pertaining to the connection"""


class TimeoutError(Exception):
    """Timing error"""


class ConfigurationError(Exception):
    """Config error"""


class CommandError(ESLError):
    """Console command error"""


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
        _log.debug("creating new logger")
        _log.propagate = True
    return _log


def get_logger(name=None):
    '''Return a sub-log for `name` or the pkg log by default
    '''
    log = get_root_log()
    return log.getChild(name) if name else log


def log_to_stderr(level=None):
    '''Turn on logging and add a handler which writes to stderr
    '''
    log = get_root_log()
    if level:
        log.setLevel(level)
    if not any(
        handler.stream == sys.stderr for handler in log.handlers
        if getattr(handler, 'stream', None)
    ):
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
                            " the colorlog module to enable\n")
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


def param2header(name):
    """Return the appropriate event header name corresponding to the named
    parameter `name` which should be used when the param is received as a
    header in event data.

    Most often this is just the original parameter name with a 'variable_'
    prefix. This is pretty much a shitty hack (thanks goes to FS for the
    asymmetry in variable referencing...)
    """
    var_keys = {
        'sip_h_X-',  # is it an x-header?
        'switchy',  # custom switchy variable?
    }
    for key in var_keys:
        if key in name:
            return 'variable_{}'.format(name)
    return name


def pstr(self):
    """Pretty str repr of connection-like instances
    """
    return '{}@{}'.format(
        type(self).__name__,
        getattr(self, 'server', getattr(self, 'host', 'unknown-host'))
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
        raise TypeError("First arg must be callable")
    if not callable(func_2):
        raise TypeError("Second arg must be callable")

    def composition(*args, **kwargs):
        return func_1(func_2(*args, **kwargs))
    return composition


def ncompose(*funcs):
    """Perform n-function composition
    """
    return functools.reduce(
        lambda f, g: lambda x: f(g(x)), funcs, lambda x: x
    )


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


def get_event_time(event, epoch=0.0):
    '''Return micro-second time stamp value in seconds
    '''
    value = event.getHeader('Event-Date-Timestamp')
    if value is None:
        get_logger().warning("Event '{}' has no timestamp!?".format(
                             event.getHeader("Event-Name")))
        return None
    return float(value) / 1e6 - epoch


class Timer(object):
    """Simple timer that reports an elapsed duration since the last reset.
    """
    def __init__(self, timer=None):
        self.time = timer or time
        self._last = 0

    def elapsed(self):
        """Returns the elapsed time since the last reset
        """
        return self.time.time() - self._last

    def reset(self):
        """Reset the timer start point to now
        """
        self._last = self.time.time()

    @property
    def last_time(self):
        '''Last time the timer was reset
        '''
        return self._last


# based on
# http://stackoverflow.com/questions/3365740/how-to-import-all-submodules
def iter_import_submods(packages, recursive=False, imp_excs=()):
    """Iteratively import all submodules of a module, including subpackages
    with optional recursion.

    :param package: package (name or actual module)
    :type package: str | module
    :rtype: (dict[str, types.ModuleType], dict[str, ImportError])
    """
    def try_import(package):
        try:
            return importlib.import_module(package)
        except ImportError as ie:
            dep = ie.message.split()[-1]
            if dep in imp_excs:
                return ie
            else:
                raise

    for package in packages:

        if isinstance(package, basestring):
            package = try_import(package)
        pkgpath = getattr(package, '__path__', None)

        if pkgpath:
            for loader, name, is_pkg in pkgutil.walk_packages(pkgpath):
                full_name = package.__name__ + '.' + name
                yield full_name, try_import(full_name)

                if recursive and is_pkg:
                    for res in iter_import_submods(
                        [full_name], recursive=recursive, imp_excs=imp_excs
                    ):
                        yield res


def waitwhile(predicate, timeout=float('inf'), period=0.1, exc=True):
    """Block until `predicate` evaluates to `False`.

    :param predicate: predicate function
    :type predicate: function
    :param float timeout: time to wait in seconds for predicate to eval False
    :param float period: poll loop sleep period in seconds
    :raises TimeoutError: if predicate does not eval to False within `timeout`
    """
    start = time.time()
    while predicate():
        time.sleep(period)
        if time.time() - start > timeout:
            if exc:
                raise TimeoutError(
                    "'{}' failed to be True".format(
                        predicate)
                )
            return False
    return True
