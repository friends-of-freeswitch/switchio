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


class AppManager(object):
    """Manage apps over a cluster/slavepool
    """
    def __init__(self, pool):
        self.pool = pool
        # attempt measurement apps setup (requires pandas)
        try:
            from measure.metrics import Measurers
        except ImportError as ie:
            if not self.log.handlers:
                utils.log_to_stderr()
            self.log.warn(ie.message)
            self.measurers = None
        else:
            # shared by whole cluster
            self.measurers = Measurers()

    def load_multi_app(self, apps_iter, app_id=None, **kwargs):
        for app in apps_iter:
            try:
                app, ppkwargs = app  # user can optionally pass doubles
            except TypeError:
                ppkwargs = {}

            # load each app under a common id (i.e. rebind with the return val)
            app_id = self.load_app(app, app_id=app_id, ppkwargs=ppkwargs,
                                   **kwargs)

        return app_id

    def load_app(self, app, app_id=None, ppkwargs={}, with_measurers=()):
        """Load and activate an app for use across all slaves in the cluster
        """
        app_id = self.pool.evals(
            'client.load_app(app, on_value=appid, **prepostkwargs)',
            app=app, appid=app_id, prepostkwargs=ppkwargs)[0]

        if self.measurers and with_measurers:
            for name, m in self.measurers.iteritems():
                for client in self.pool.clients:
                    if name not in client._apps[app_id]:
                        storer = m.get_storer()
                        client.load_app(
                            m.app,
                            on_value=app_id,
                            storer=storer,
                            **m.ppkwargs
                        )
                        self.measurers.add_storer(name, storer, app_id)

        return app_id

    def iterapps(self):
        """Iterable over all unique contained subapps
        """
        return set(
            app for app_map in itertools.chain.from_iterable(
                self.pool.evals('client._apps.values()')
            )
            for app in app_map.values()
        )
