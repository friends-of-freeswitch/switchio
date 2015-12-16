# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This module includes helpers for capturing measurements using pandas.
"""
import traceback
import signal
import atexit
import itertools
import tempfile
import pandas as pd
import numpy as np
import shmarray
import os
import pickle
from switchy import utils
from functools import partial
from collections import OrderedDict, namedtuple
import multiprocessing as mp
from multiprocessing import queues
import time

# use the entire screen width + wrapping
pd.set_option('display.expand_frame_repr', False)
# app names should generally be shorter then this...
min_size = 30


def DictProxy(d, extra_attrs={}):
    """A dictionary proxy object which provides attribute access to elements
    """
    attrs = [
        '__repr__',
        '__getitem__',
        '__setitem__',
        '__contains__',
    ]
    attr_map = {attr: getattr(d, attr) for attr in attrs}
    attr_map.update(extra_attrs)
    proxy = type('DictProxy', (), attr_map)()
    proxy.__dict__ = d
    return proxy


def moving_avg(x, n=100):
    '''Compute the windowed arithmetic mean of `x` with window length `n`
    '''
    n = min(x.size, n)
    cs = np.cumsum(x)
    cs[n:] = cs[n:] - cs[:-n]
    # cs[n - 1:] / n  # true means portion
    return cs / n  # NOTE: first n-2 vals are not true means


def plot_df(df, figspec, **kwargs):
    """Plot a pandas data frame according to the provided `figspec`
    """
    from mpl_helpers import multiplot
    return multiplot(df, figspec=figspec, **kwargs)


Measurer = namedtuple("Measurer", 'app ppkwargs storer ops')


class Measurers(object):
    """A dict-like collection of measurement apps with
    sub-references to each app's `DataStorer` and optional metrics
    computing callables.

    The purpose of this type is two-fold:
    1) provide micro-management of apps which collect data/measurements
    (measurers) such that they can be loaded and referenced as a group under
    different scopes (eg. per call control app).
    2) provide an interface for adding operator functions which process
    a single pandas.DataFrame and provide a new frame output for analysis.

    Each `Measurer` tuple can be accessed using dict-like subscript syntax.
    """
    def __init__(self):
        self._apps = OrderedDict()
        # delegate to `_apps` for subscript access
        for meth in '__getitem__ __contains__'.split():
            setattr(self.__class__, meth, getattr(self._apps, meth))

        # add attr access for references to data frame operators
        self._ops = OrderedDict()
        self.ops = DictProxy(self._ops)
        # do the same for data stores
        self._stores = OrderedDict()
        self.stores = DictProxy(self._stores)
        # same for figspecs
        self._figspecs = OrderedDict()
        self.figspecs = DictProxy(self._figspecs)

    def __repr__(self):
        return repr(self._apps).replace(
            type(self._apps).__name__, type(self).__name__)

    def add(self, app, name=None, operators={}, **ppkwargs):
        name = name or utils.get_name(app)
        prepost = getattr(app, 'prepost', None)
        if not prepost:
            raise AttributeError(
                "'{}' must define a `prepost` method".format(name))
        args, kwargs = utils.get_args(app.prepost)
        if 'storer' not in kwargs:
            raise TypeError("'{}' must define a 'storer' kwarg"
                            .format(app.prepost))

        # acquire storer factory
        factory = getattr(app, 'new_storer', None)
        storer_kwargs = getattr(app, 'storer_kwargs', {})
        # app may not define a storer factory method
        storer = DataStorer(
                name, dtype=app.fields, **storer_kwargs
        ) if not factory else factory()

        self._apps[name] = Measurer(app, ppkwargs, storer, {})
        # provide attr access off `self.stores`
        self._stores[name] = storer
        setattr(
            self.stores.__class__,
            name,
            # make instance lookups access the `data` attr
            property(partial(storer.__class__.data.__get__, storer))
        )
        # add any app defined operator functions
        ops = getattr(app, 'operators', {})
        ops.update(operators)
        for opname, func in ops.items():
            self.add_operator(name, func, opname=opname)

        return name

    def add_operator(self, measurername, func, opname):
        m = self._apps[measurername]
        m.ops[opname] = func

        def operator(self, storer):
            return storer.data.pipe(func)

        # provides descriptor protocol access for interactive work
        self._ops[opname] = func
        setattr(self.ops.__class__, opname,
                property(partial(operator, storer=m.storer)))

        # append any figure specification
        figspec = getattr(func, 'figspec', None)
        if figspec:
            self._figspecs[opname] = figspec

    def items(self):
        return list(reversed(self._apps.items()))

    def to_store(self, dirpath):
        """Dump all data + operator combinations to a hierarchical HDF store
        on disk.
        """
        if not os.path.isdir(dirpath):
            raise ValueError("You must provide a directory")

        storepath = os.path.join(dirpath, "switchy_measures.hdf5")
        with pd.HDFStore(storepath) as store:
            # raw data sets
            for name, m in self._apps.items():
                data = m.storer.data
                if len(data):
                    store.append(
                        "{}".format(name), data, min_itemsize=min_size)

                    # processed (metrics) data sets
                    for opname, op in m.ops.items():
                        store.append(
                            '{}/{}'.format(name, opname),
                            op(data),
                            dropna=False,
                            min_itemsize=min_size,
                        )
        # dump pickle file containing figspec (and possibly other meta-data)
        pklpath = os.path.join(dirpath, 'switchy_measure.pkl')
        with open(pklpath, 'w') as pklfile:
            pickle.dump(
                {'storepath': storepath, 'figspecs': self._figspecs},
                pklfile,
            )
        return pklpath

    @property
    def merged_ops(self):
        """Merge and return all function operator frames from all measurers
        """
        # concat along the columns
        return pd.concat(
            (getattr(self.ops, name) for name in self._ops),
            axis=1
        )

    def plot(self, **kwargs):
        """Plot all figures specified in the `figspecs` dict.
        """
        return [
            (figspec, plot_df(self.merged_ops, figspec, **kwargs))
            for figspec in self._figspecs.values()
        ]


def mkhdf(path=None, mode='a'):
    # disk storage via HDF
    path = path or tempfile.mktemp() + '_switchy_data.h5'
    store = pd.HDFStore(path, mode)
    return store


class Terminate(Exception):
    """"A unique error type to trigger writer proc termination
    """


class DataStorer(object):
    """Wraps a `pd.DataFrame` which buffers recent data in memory and
    offloads excess to disk using the HDF5 format.
    """
    def __init__(self, name, dtype, data=None, buf_size=2**10, hdf_path=None,
                 bg_writer=True):
        self.name = name
        try:
            self.dtype = np.dtype(dtype)
        except TypeError:
            # set all columns to float64
            self.dtype = np.dtype(zip(dtype, itertools.repeat(np.float64)))

        if data is None:
            # allocated a shared mem np structured array
            self._shmarr = shmarray.create(buf_size, dtype=self.dtype)
        else:
            # whatever array was passed in (eg. loaded data)
            self._shmarr = np.array(data)
            bg_writer = False

        self._len = len(self._shmarr)
        self.log = utils.get_logger(type(self).__name__)
        # shared current row insertion-index
        self._iput = 0
        self._ri = mp.Value('i', 0 if data is None else self._len, lock=False)

        # parent proc read-only access to disk store
        self._store = mkhdf(hdf_path)
        self._store.close()

        # setup bg writer
        self.queue = queues.SimpleQueue()
        if bg_writer:
            # disable SIGINT while we spawn
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            self._writer = mp.Process(
                target=_consume_and_write,
                args=(
                    self.queue, self._store.filename, self._ri,
                    self._shmarr),
                name='{}_frame_writer'.format(self.name),
            )
            self._writer.start()
            # re-enable SIGINT
            signal.signal(signal.SIGINT, signal.default_int_handler)
            # kill subproc on exit
            atexit.register(self._stopwriter)

    @property
    def store(self):
        """HDF5 Store for offloading data to disk
        """
        self._store.open('r')
        return self._store

    @property
    def buffer(self):
        """The latest set of buffered data points not yet pushed to disk
        """
        return pd.DataFrame.from_records(self._shmarr[:self.buflen])

    @property
    def data(self):
        """Copy of the entire data set recorded thus far
        """
        if self.store.keys():
            return pd.concat(
                (self.store['data'], self.buffer),
                ignore_index=True
            )
        return self.buffer

    @property
    def buflen(self):
        """Current buffer length up the last inserted data point
        """
        bi = self.bindex
        l = self._len
        if not bi:
            # handles the 1 % 1 == 0 case when l == 1
            return bi if self.rindex < l else l
        return bi

    @property
    def rindex(self):
        '''Current absolute row insertion index
        '''
        return self._ri.value

    @property
    def bindex(self):
        """Current insertion index of in mem frame buffer
        (i.e. the index where the next value should be inserted)
        """
        return self._ri.value % self._len

    def append_row(self, row=None):
        """Push a row of data onto the consumer queue
        """
        start = time.time()
        self.queue.put(row)
        self._iput += 1
        diff = time.time() - start
        if diff > 0.005:  # any more then 5ms warn the user
            self.log.warn("queue.put took '{}' seconds".format(diff))

    def _stopwriter(self):
        """Trigger the background frame writer to terminate
        """
        self.queue.put(Terminate)


def _consume_and_write(queue, path, ri, sharr):
    '''Insert :var:`row` pushed onto the queue into the internal data
    frame at the current index and increment.
    Return a boolean indicating whether the current entry
    has caused a flush to disk. Empty rows are always written to disk
    (keeps stores 'call-index-aligned').
    '''
    proc = mp.current_process()
    slog = utils.get_logger(proc.name)
    log = mp.log_to_stderr(slog.getEffectiveLevel())
    log.info("hdf path is '{}'".format(path))
    log.info("starting frame writer '{}'".format(proc.name))

    # set up child process HDF store
    store = mkhdf(path)
    store.open('a')
    _len = len(sharr)

    # consume and process
    for row in iter(queue.get, Terminate):
        now = time.time()
        i = ri.value % _len
        if ri.value > _len - 1 and i == 0:
            # write frame to disk on buffer fill
            log.debug('writing with pytables...')
            try:
                store.append(
                    'data',
                    pd.DataFrame.from_records(sharr),
                    dropna=False,
                    min_itemsize=min_size,
                )
                store.flush(fsync=True)
            except ValueError:
                log.error(traceback.format_exc())
            log.debug("disk write took '{}'".format(time.time() - now))
        try:
            # insert into numpy structured array by row int-index
            sharr[i] = row
            log.debug("shmarray insert took '{}'".format(time.time() - now))
            # increment row insertion index for the next entry (this means
            # the last entry is at now at i - 1)
            ri.value += 1
        except ValueError:
            log.error(traceback.format_exc())

    store.close()
    log.debug("terminating frame writer '{}'".format(proc.name))


def load(path):
    """Load a previously pickled data set from the filesystem and return it as
    a loaded `pandas.DataFrame`.
    """
    with open(path, 'r') as pkl:
        obj = pickle.load(pkl)
        if not isinstance(obj, dict):
            return load_legacy(obj)

        store = pd.HDFStore(obj['storepath'])
        merged = pd.concat(
            (store[key] for key in store.keys()),
            axis=1,
        )
        figspecs = obj.get('figspecs', {})
        # XXX evetually we should support multiple figures
        figspec = figspecs[figspecs.keys()[0]]
        merged._plot = partial(plot_df, merged, figspec)
        return merged


def load_legacy(array):
    '''Load a pickeled numpy structured array from the filesystem into a
    `DataFrame`.
    '''
    # calc and assign rate info
    def calc_rates(df):
        df = df.sort(['time'])
        mdf = pd.DataFrame(
            df, index=range(len(df))).assign(hangup_index=df.index).assign(
            inst_rate=lambda df: 1 / df['time'].diff()
        ).assign(
            wm_rate=lambda df: pd.rolling_mean(df['inst_rate'], 30)
        )
        return mdf

    # adjust field spec to old record array record names
    figspec = {
        (1, 1): [
            'call_setup_latency',
            'answer_latency',
            'invite_latency',
            'originate_latency',
        ],
        (2, 1): [
            'num_sessions',
            'num_failed_calls',
        ],
        (3, 1): [
            'inst_rate',
            'wm_rate',  # why so many NaN?
        ]
    }
    df = calc_rates(pd.DataFrame.from_records(array))
    df._plot = partial(plot_df, df, figspec)
    return df
