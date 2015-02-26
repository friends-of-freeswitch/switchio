# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Proxies for shared freeswitch objects
"""
import functools
import signal
from collections import OrderedDict
import multiprocessing as mp
from multiprocessing import managers, util
# from multiprocessing.managers import State, DictProxy
from utils import get_logger
from . import utils


# mp debugging
_log_level = None


def set_debug(toggle=True):
    global _log_level
    logger = mp.log_to_stderr()
    if toggle:
        # _log_level = logger.getLevel()
        logger.setLevel('DEBUG')
    # else:
    #     logger.setLevel(_log_level)


# "transparent" proxy methods
def _repr(self):
    return self._callmethod('__repr__')


def _proxy_dir(self):
    try:  # to get the proxy listing
        attrs = self._callmethod('__dir__')
    except IOError:
        assert not self._manager._process.is_alive(),\
            "Mng is alive but proxy received IOerror!?"
        raise RuntimeError("the proxy mng has died?!")
    except managers.RemoteError:
        attrs = dir(type(self))
    # attrs.extend(self.exposed)
    attrs.extend(utils._dir(self))
    return attrs


def make_inst_proxy(cls, exposed=None, method_to_typeid=None):
    '''
    Return a custom proxy for wrapping access to a shared instance

    Parameters
    ----------
    cls : type
        Class for which a proxy object should be created
    exposed : list
        Sequence of methods which should be made public via the proxy
        object.  If not provided public methods are automatically
        retrieved from the class' declared interface

    Returns
    -------
    proxy : a subclass of mp.managers.BaseProxy with a getattr/setattr
        interface (see mp.managers.py for details)
    '''
    if exposed is None:
        try:
            exposed = cls._exposed
        except AttributeError:
            exposed = managers.public_methods(cls)

    # auto-attach listed methods
    ProxyBase = managers.MakeProxyType('ProxyBase', exposed)

    # make mutable to extend
    exposed = list(ProxyBase._exposed_)

    class InstProxy(ProxyBase):
        _exposed_ = tuple(exposed + ['__getattribute__', '__setattr__',
                                     '__dir__'])
        _attr_redirect = {}

        __repr__ = _repr

        __dir__ = _proxy_dir

        def __getattr__(self, key):
            try:
                return object.__getattribute__(self, key)
            except AttributeError:
                callmethod = object.__getattribute__(self, '_callmethod')
                # handle attr redirects declared by this proxy
                if key in self._attr_redirect:
                    method = self._attr_redirect[key]
                    return callmethod(method)
                else:
                    method = '__getattribute__'
                    return callmethod(method, (key,))

        def __setattr__(self, key, value):
            if key[0] == '_':  # this is critical do not change
                return object.__setattr__(self, key, value)
            else:
                callmethod = object.__getattribute__(self, '_callmethod')
                return callmethod('__setattr__', (key, value))

    # mark shared 'sub-proxy' attributes
    if method_to_typeid:
        InstProxy._method_to_typeid_.update(method_to_typeid)

    return InstProxy


# override the default manager to catch a weird OSError and
# add some functionality
class CustomSyncMng(managers.SyncManager):

    @staticmethod
    def _finalize_manager(process, address, authkey, state, _Client):
        '''
        Shutdown the manager process; will be registered as a finalizer
        '''
        if process.is_alive():
            util.info('sending shutdown message to manager')
            try:
                conn = _Client(address, authkey=authkey)
                try:
                    managers.dispatch(conn, None, 'shutdown')
                finally:
                    conn.close()
            except Exception:
                pass

            process.join(timeout=0.2)
            if process.is_alive():
                util.info('manager still alive')
                if hasattr(process, 'terminate'):
                    util.info('trying to `terminate()` manager process')

                    try:
                        process.terminate()
                        process.join(timeout=0.1)
            # XXX: catch the OS error ... something weird is going on here..
                    except OSError:
                        pass
                    if process.is_alive():
                        util.info('manager still alive after terminate')

        state.value = managers.State.SHUTDOWN
        try:
            del managers.BaseProxy._address_to_local[address]
        except KeyError:
            pass

    @functools.wraps(managers.BaseManager.start)
    def start(self, *args, **kwargs):
        try:
            # disable SIGINT while we spawn
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            super(self.__class__, self).start(*args, **kwargs)
        finally:
            # re-enable SIGINT
            signal.signal(signal.SIGINT, signal.default_int_handler)

    @classmethod
    def auto_register(mng_cls, cls, proxytype=None, init_args=(),
                      init_kwargs={}, **kwargs):
        '''
        Register shared object classes with a default proxytype.

        Parameters
        ----------
        cls : type
            class which is to be registered with the manager for use
            as a shared object
        proxytype : subclass of multiprocessing.managers.BaseProxy
            Proxy object used to communicate with a shared instance of cls.
            If None, then the following steps are attempted:
            1) an attempt is made to call the class' build_proxy method which
               is expected to provision and return a proxy object as well as
               register with the manager any sub-proxies which it expects to
               utilize.
            2) failing that, a default -> make_inst_proxy(cls) will be used.
        '''
        assert type(cls) == type
        typeid = cls.__name__
        if proxytype is None:
            try:  # to use cls defined proxy
                proxytype = cls.build_proxy(mng_cls)
            except AttributeError:
                proxytype = make_inst_proxy(cls)
                get_logger().debug("no proxy was provided for '{}' using "
                                   "default '{}'".format(cls, proxytype))

        cls = functools.partial(cls, *init_args, **init_kwargs)
        mng_cls.register(typeid, cls, proxytype=proxytype, **kwargs)


# Register some more useful shared types
CustomSyncMng.register('MpLock', mp.Lock, managers.AcquirerProxy)


class OrderedDictProxy(managers.DictProxy):
    __dir__ = _proxy_dir
    __repr__ = _repr

CustomSyncMng.register('OrderedDict', OrderedDict, OrderedDictProxy)


def dict_of_proxies(value_type, mng, dict_typeid='OrderedDict'):
    assert type(value_type) == type
    name = value_type.__name__
    assert name in mng._registry
    dicttype, exp, meth_to_type, dictproxytype = mng._registry[dict_typeid]
    proxy_name = '{}sDictProxy'.format(name)
    # make a new subclass of the specified dict proxy type
    # and make it contain sub-proxies of value_type
    proxytype = type(proxy_name, (dictproxytype,), {})
    proxytype._method_to_typeid_ = {'__getitem__': name}
    mng.register(proxy_name, dicttype, proxytype)
    return proxy_name, proxytype


def get_mng(address=None, authkey=None, proxy_map={},
            _mng_type=CustomSyncMng,
            _mng_cache={}, **kwargs):
    '''
    Return a custom multiprocessing.mangers proxy manager which has
    some extra features.

    Parameters
    ----------
    proxy_map : map
        An optional map of python objects to proxy objects which will
        immediately be 'auto registered' with the requested manager.
        Proxies must inherit from multiprocessing.managers.BaseProxy
    kwargs : same as for mp.BaseManager

    Returns
    -------
    mng : instance of {} by default
    '''.format(_mng_type)
    try:
        addr = kwargs.get('address', None)
        mng = _mng_cache[addr]
    except KeyError:
        # TODO: calls to rypc if address is not found on this host
        # eg. if kwargs['address'] not on localhost: rpyc.connect()
        mng = _mng_type(**kwargs)
        _mng_cache[addr] = mng

    # register shared objects with mng cls
    for cls, proxy in proxy_map.items():
        mng.auto_register(cls, proxytype=proxy, **kwargs)
    return mng
