# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Built-in applications
'''
from .. import utils, marks
from collections import OrderedDict
import itertools
import operator

# registry
_apps = OrderedDict()


def app(*args, **kwargs):
    '''Decorator to register switchy application classes.
       Example usage:

       @app
       class CoolAppController(object):
           pass

       This will register the class as a switchy app.
       The name of the app defaults to `class.__name__`.
       The help for the app is taken from `class.__doc__`.

       You can also provide an alternative name via a
       decorator argument:

       @app('CoolName')
       class CoolAppController(object):
           pass

       or with a keyword arg:

       @app(name='CoolName')
       class CoolAppController(object):
           pass
    '''
    name = kwargs.get('name')
    if len(args) >= 1:
        arg0 = args[0]
        if type(arg0) is type:
            return register(arg0, None)
        name = arg0
        # if len(args) > 1:
        #     tail = args[1:]

    def inner(cls):
        return register(cls, name=name)
    return inner


def register(cls, name=None):
    """Register an app in the global registry
    """
    if not marks.has_callbacks(cls):
        raise ValueError(
            "{} contains no defined handlers or callbacks?".format(cls)
        )
    app = _apps.setdefault(name or cls.__name__, cls)
    if cls is not app:
        raise ValueError("An app '{}' already exists with name '{}'"
                         .format(app, name))
    return cls


def iterapps():
    """Iterable over all registered apps.
    """
    return itertools.chain(_apps.values())


def groupbymod():
    """Return an iterable which delivers tuples (<modulename>, <apps_subiter>)
    """
    return itertools.groupby(
        _apps.items(),
        utils.compose(
            operator.attrgetter('__module__'),
            operator.itemgetter(1)
        )
    )


def get(name):
    """Get a registered app by name or None if one isn't registered.
    """
    return _apps.get(name)


def load(packages=(), imp_excs=('numpy',)):
    """Load by importing all built-in apps along with any apps found in the
    provided `packages` list.

    :param packages: package (names or actual modules)
    :type package: str | module
    :rtype: dict[str, types.ModuleType]
    """
    apps_map = {}
    # load built-ins + extras
    for path, app in utils.iter_import_submods(
        (__name__,) + packages,
        imp_excs=imp_excs,
    ):
        if isinstance(app, ImportError):
            utils.log_to_stderr().warn("'{}' failed to load - {}\n".format(
                path, app.message))
        else:
            apps_map[path] = app
    return apps_map
