# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
ESL client API
"""
import time
import inspect
import functools
import weakref
from contextlib import contextmanager
from collections import deque, namedtuple

# NOTE: the import order matters here!
from . import utils
from . import handlers
from .utils import ConfigurationError, APIError
from .commands import build_originate_cmd
from . import marks
from .connection import get_connection, ConnectionError


class Client(object):
    '''Interface for synchronous server control using the esl "inbound method"
    as described here:
    https://wiki.freeswitch.org/wiki/Mod_event_socket#Inbound

    Provides a high level api for registering apps, originating calls, and
    managing an event listener and its event loop.
    '''
    app_id_header = utils.xheaderify('switchy_app')

    def __init__(self, host='127.0.0.1', port='8021', auth='ClueCon',
                 call_tracking_header=None, listener=None, logger=None):
        self.host = host
        self.port = port
        self.auth = auth
        # works under the assumption that x-headers are forwarded by the proxy
        self.call_tracking_header = call_tracking_header or utils.xheaderify(
            'switchy_originating_session')

        self._id = utils.uuid()
        self._orig_cmd = None
        self.log = logger or utils.get_logger(utils.pstr(self))
        # clients can host multiple "composed" apps
        self._apps = {}
        self.apps = type('apps', (), {})()
        self.apps.__dict__ = self._apps  # dot-access to `_apps` from `apps`
        self.client = self  # for app funcarg insertion

        # WARNING: order of these next steps matters!
        # create a local connection for sending commands
        self._con = get_connection(self.host, self.port, self.auth)
        # if the listener is provided it is expected that the
        # user will run the set up methods (i.e. connect, start, etc..)
        self.listener = listener

    __repr__ = utils.con_repr

    def get_listener(self):
        if self._listener:
            return self._listener
        else:
            raise AttributeError(
                "No listener has been assigned for this client")

    def set_listener(self, inst):
        self._listener = inst
        if inst:
            # with asyncio use this listener's transmitting connection for all comms
            if getattr(inst.event_loop, '_run_loop', None):
                self._con = inst._tx_con
            # Set the listener's call tracking header
            self._listener.call_tracking_header = utils.param2header(
                self.call_tracking_header)
            self.log.debug("set call lookup variable to '{}'".format(
                self._listener.call_tracking_header))

    listener = property(get_listener, set_listener,
                        'Reference to the underlying EventListener')

    def get_loglevel(self):
        token, num = self.cmd(
            'fsctl loglevel').rpartition(':')[-1].split()
        num = num.strip('[]')
        return token, num

    def set_loglevel(self, value):
        self.cmd('fsctl loglevel {}'.format(value))

    loglevel = property(get_loglevel, set_loglevel)

    def load_app(self, ns, on_value=None, header=None, prepend=False,
                 funcargsmap=None, **prepost_kwargs):
        """Load annotated callbacks and from a namespace and add them
        to this client's listener's callback chain.

        :param ns: A namespace-like object containing functions marked with
            @event_callback (can be a module, class or instance).
        :params str on_value: app group id key to be used for registering app
            callbacks with the `EventListener`. This value will be inserted in
            the `originate` command as an X-header and used to look up which
            app callbacks should be invoked for each received event.
        """
        listener = self.listener
        name = utils.get_name(ns)
        group_id = on_value or name or utils.uuid()
        app_map = self._apps.get(group_id, None)
        if app_map and name in app_map and group_id != 'default':
            # only allow 1 app inst per group
            raise ConfigurationError(
                "an app instance with name '{}' already exists for app group "
                "'{}'.\nIf you want multiple instances of the same app load "
                "them using different `on_value` ids."
                .format(name, group_id)
            )

        # if handed a class, instantiate appropriately
        app = ns() if isinstance(ns, type) else ns

        # handle prepost-fixture setup/teardown
        prepost = getattr(app, 'prepost', False)
        if prepost:
            funcargsmap = funcargsmap or {}
            # deliver args declared in the function signature
            args, kwargs = utils.get_args(app.prepost)
            funcargs = []
            for argname in args:
                if argname == 'self':
                    continue
                funcargs.append(weakref.proxy(
                    funcargsmap.get(argname) or getattr(self, argname)))

            ret = prepost(*funcargs, **prepost_kwargs)
            if inspect.isgenerator(ret):
                # run init step
                next(ret)
                app._finalize = ret

        self.log.info(
            "Loading '{}' app with group id '{}' for event_loop '{}'"
            .format(name, group_id, listener.event_loop)
        )
        failed = False
        cb_paths = []
        handler_paths = []
        # insert handlers and callbacks
        for ev_type, cb_type, obj in marks.get_callbacks(app):
            if cb_type == 'handler':
                # TODO: similar unloading on failure here as above?
                listener.event_loop.add_handler(ev_type, obj)
                handler_paths.append(ev_type, obj)

            elif cb_type == 'callback':
                # add default handler if none exists
                if ev_type not in listener.event_loop._handlers:
                    self.log.info(
                        "adding default session lookup handler for event"
                        " type '{}'".format(ev_type)
                    )
                    listener.event_loop.add_handler(
                        ev_type,
                        listener.lookup_sess
                    )
                added = listener.event_loop.add_callback(
                    ev_type, group_id, obj, prepend=prepend)
                if not added:
                    failed = obj
                    for path in reversed(cb_paths):
                        listener.event_loop.remove_callback(*path)
                    break
                cb_paths.append((ev_type, group_id, obj))
                self.log.debug("'{}' event callback '{}' added for id '{}'"
                               .format(ev_type, obj.__name__, group_id))

        if failed:
            raise TypeError("App load failed since '{}' is not a valid"
                            "callback type".format(failed))
        if not cb_paths and not handler_paths:
            raise TypeError(
                "Failed to load '{}' no callbacks or handlers could be found"
                .format(name)
            )

        # prepend the provided header to use for app id look ups
        # TODO: should probably be moved into `add_callback()`?
        header = header or utils.param2header(self.app_id_header)
        if header not in listener.event_loop.app_id_headers:
            listener.event_loop.app_id_headers.insert(0, header)
            self.log.debug("app id var '{}' prepended to {}"
                           .format(header, listener.event_loop))

        # register locally
        self._apps.setdefault(group_id, {})[name] = app
        app.cid, app.name = group_id, name
        return group_id

    def unload_app(self, on_value, ns=None):
        """Unload all callbacks associated with a particular app
        `on_value` id.
        If `ns` is provided unload only the callbacks from that particular
        subapp.
        """
        app_map = self._apps.get(on_value)
        if app_map is None:
            self.log.debug("app for id {} was already unloaded".format(
                on_value))
            return

        appkeys = [utils.get_name(ns)] if ns else list(app_map.keys())

        for name in appkeys:
            app = app_map.pop(name)
            # run prepost teardown
            finalize = getattr(app, '_finalize', False)
            if finalize:
                try:
                    next(finalize)
                except StopIteration:
                    pass
            # remove callbacks
            for ev_type, cb_type, obj in marks.get_callbacks(app):
                # XXX we need a sane way to remove handlers as well!
                if cb_type == 'callback':
                    self.listener.event_loop.remove_callback(
                        ev_type, on_value, obj)

        if not app_map:
            self._apps.pop(on_value)

    def disconnect(self):
        """Disconnect the client's underlying connection
        """
        self._con.disconnect()
        time.sleep(0.1)

    def connect(self):
        """Connect this client
        """
        self._con.connect()
        assert self.connected(), "Failed to connect to '{}'".format(
            self.host)

    def connected(self):
        """Check if connection is active
        """
        return self._con.connected()

    def api(self, cmd, exc=True):
        '''Invoke esl api command with error checking
        Returns an ESL.ESLEvent instance for event type "SOCKET_DATA".
        '''
        # NOTE api calls do not require an event loop
        # since we can handle the event processing synchronously
        try:
            event = self._con.api(cmd)
        except APIError:
            if exc:
                raise
        return event

    def cmd(self, cmd):
        '''Return the string-body output from invoking a command
        '''
        return self._con.cmd(cmd)

    def hupall(self, group_id=None):
        """Hangup all calls associated with this client
        by iterating all managed call apps and hupall-ing
        with the apps callback id. If :var:`group_id` is provided
        look up the corresponding app an hang up calls for that
        specific app.
        """
        if not group_id:
            # hangup all calls for all apps
            for group_id in self._apps:
                self.api('hupall NORMAL_CLEARING {} {}'.format(
                         self.app_id_header, group_id))
        else:
            self.api('hupall NORMAL_CLEARING {} {}'.format(
                     self.app_id_header, group_id))

    def _assert_alive(self, listener=None):
        """Assert our listener's event loop is active and if so return it
        """
        listener = listener or self.listener
        if not listener.event_loop.is_alive():
            raise ConfigurationError(
                "start this {} before issuing bgapi"
                .format(listener.event_loop)
            )
        return listener

    def bgapi(self, cmd, listener=None, callback=None, client_id=None,
              **jobkwargs):
        '''Execute a non blocking api call and handle it to completion

        Parameters
        ----------
        cmd : string
            command to execute
        listener : ``EventListener`` instance
            session listener which will handle bg job events for this cmd
        callback : callable
            Object to call once the listener collects the bj event result.
            By default the listener calls back the job instance with the
            response from the 'BACKGROUND_JOB' event's body content plus any
            kwargs passed here.
        '''
        listener = self._assert_alive(listener)
        # block the event loop while we insert our job
        listener.block_jobs()
        con = listener._tx_con
        try:
            ev = con.bgapi(cmd)
            if ev:
                bj = listener.register_job(
                    ev, callback=callback,
                    client_id=client_id or self._id,
                    **jobkwargs
                )
            else:
                if not con.connected():
                    raise ConnectionError("local connection down on '{}'!?"
                                          .format(con.host))
                else:
                    raise APIError("bgapi cmd failed?!\n{}".format(cmd))
        finally:
            # wakeup the listener's event loop
            listener.unblock_jobs()
        return bj

    def originate(self, dest_url=None,
                  uuid_func=utils.uuid,
                  app_id=None,
                  listener=None,
                  bgapi_kwargs={},
                  rep_fields={},
                  **orig_kwargs):
        '''Originate a call using FreeSWITCH 'originate' command.
        A non-blocking bgapi call is used by default.

        Parameters
        ----------
        see :func:`build_originate_cmd`

        orig_kwargs: additional originate cmd builder kwargs forwarded to
            :func:`build_originate_cmd` call

        Returns
        -------
        instance of `Job` a background job
        '''
        listener = self._assert_alive(listener)
        # gen originating session uuid for tracking call
        uuid_str = uuid_func()
        if dest_url:  # generate the cmd now
            origkwds = {self.app_id_header: app_id or self._id}
            origkwds.update(orig_kwargs)
            cmd_str = build_originate_cmd(
                dest_url,
                uuid_str=uuid_str,
                xheaders={self.call_tracking_header: uuid_str},
                **origkwds
            )
        else:  # accept late data insertion for the uuid_str and app_id
            cmd_str = self.originate_cmd.format(
                uuid_str=uuid_str,
                app_id=app_id or self._id,
                **rep_fields
            )

        return self.bgapi(
            cmd_str, listener,
            sess_uuid=uuid_str,
            client_id=app_id,
            **bgapi_kwargs
        )

    @functools.wraps(build_originate_cmd)
    def set_orig_cmd(self, *args, **kwargs):
        '''Build and cache an originate cmd string for later use
        as the default input for calls to `originate`
        '''
        # by default this inserts a couple placeholders which can be replaced
        # at run time by a format(uuid_str='blah', app_id='foo') call
        xhs = {}
        if self.listener:
            xhs[self.call_tracking_header] = '{uuid_str}'
        xhs.update(kwargs.pop('xheaders', {}))  # overrides from caller

        origparams = {self.app_id_header: '{app_id}'}
        if 'uuid_str' in kwargs:
            raise ConfigurationError(
                "passing 'uuid_str' here is improper usage")
        origparams.update(kwargs)

        # build a reusable command string
        self._orig_cmd = build_originate_cmd(
            *args,
            xheaders=xhs,
            **origparams
        )

    @property
    def originate_cmd(self):
        return self._orig_cmd


@contextmanager
def get_client(host, port='8021', auth='ClueCon', apps=None):
    '''A context manager which delivers an active `Client` containing a started
    `EventListener` with applications loaded that were passed in the `apps` map
    '''
    client = Client(
        host, port, auth, listener=handlers.get_listener(host, port, auth)
    )
    client.listener.connect()
    client.connect()

    # TODO: maybe we should (try to) use the app manager here?
    # load app set
    if apps:
        if getattr(apps, 'items', None):
            apps = apps.items()

        for on_value, app in apps:
            try:
                app, ppkwargs = app  # user can optionally pass doubles
            except TypeError:
                ppkwargs = {}
            # doesn't currently load "composed" apps
            client.load_app(
                app,
                on_value=on_value,
                **ppkwargs
            )
    # client setup/teardown
    client.listener.start()
    yield client

    # unload app set
    if apps:
        for value, app in apps:
            client.unload_app(value)

    client.listener.disconnect()
    client.disconnect()


# legacy alias
active_client = get_client


def get_pool(contacts, **kwargs):
    """Construct and return a slave pool from a sequence of
    contact information.
    """
    assert not isinstance(contacts, str)
    from .distribute import SlavePool
    SlavePair = namedtuple("SlavePair", "client listener")
    pairs = deque()

    # instantiate all pairs
    for contact in contacts:
        if isinstance(contact, str) or isinstance(contact, unicode):
            contact = (contact,)

        # create pairs
        listener = handlers.get_listener(*contact, **kwargs)

        # extract client only kwargs
        _, kwargnames = utils.get_args(Client.__init__)
        clientonly = {
            name: kwargs[name] for name in kwargnames if name in kwargs}

        client = Client(
            *contact,
            listener=listener,
            **clientonly
        )
        pairs.append(SlavePair(client, listener))

    return SlavePool(pairs)
