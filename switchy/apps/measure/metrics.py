# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This module includes helpers for capturing measurements using pandas.
"""
import traceback
import signal
import atexit
import tempfile
import pandas as pd
import numpy as np
from switchy import utils
from functools import partial
from collections import OrderedDict, namedtuple
import multiprocessing as mp
from multiprocessing.queues import SimpleQueue
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
        setattr(self.__class__, '__getitem__',
                getattr(self._apps, '__getitem__'))

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
        args, kwargs = utils.get_args(app.prepost)
        if 'storer' not in kwargs:
            raise TypeError("'{}' must define a 'storer' kwarg"
                            .format(app.prepost))
        name = name or utils.get_name(app)

        # acquire storer factory
        factory = getattr(app, 'new_storer', None)
        storer_kwargs = getattr(app, 'storer_kwargs', {})
        # app may not define a storer factory method
        storer = DataStorer(
                name, columns=app.fields,
                **storer_kwargs
        ) if not factory else factory()

        self._apps[name] = Measurer(app, ppkwargs, storer, {})
        # provide attr access off `self.stores`
        self._stores[name] = storer
        setattr(
            self.stores.__class__,
            name,
            property(partial(storer.__class__.data.__get__, storer))
        )

        # add any app defined operator functions
        ops = getattr(app, 'operators', {})
        ops.update(operators)
        for opname, func in ops.items():
            self.add_operator(name, func, opname=opname)

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

    def to_store(self, path):
        """Dump all data + operator combinations to a hierarchical HDF store
        on disk.
        """
        with pd.HDFStore(path) as store:
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
    def __init__(
        self, name, data=None, columns=None, buf_size=2**10,
        dtype=None, hdf_path=None, bg_writer=True
    ):
        self.name = name
        self._df = pd.DataFrame(
            data=data,
            columns=columns,
            index=range(buf_size) if data is None else None,
            dtype=dtype,
        )
        self._len = len(self._df)
        self.log = utils.get_logger(type(self).__name__)
        # shared current row insertion-index
        self._iput = 0
        self._ri = mp.Value('i', 0 if data is None else len(self._df) - 1,
                            lock=False,)

        # parent proc read-only access to disk store
        self._store = mkhdf(hdf_path)
        self._store.close()

        # setup bg writer
        self.queue = SimpleQueue()
        if bg_writer:
            # disable SIGINT while we spawn
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            self._writer = mp.Process(
                target=_consume_and_write,
                args=(self.queue, self._store.filename, self._ri, self._df),
                name='{}_frame_writer'.format(self.name),
            )
            self._writer.start()
            # re-enable SIGINT
            signal.signal(signal.SIGINT, signal.default_int_handler)

        # kill subproc on exit
        atexit.register(self.stop)

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
        return self._df[:self.bindex].apply(lambda df: df.astype('object'))

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
    def rindex(self):
        '''Current absolute row index
        '''
        return self._ri.value

    @property
    def bindex(self):
        """Current index of in mem frame buffer
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

    def stop(self):
        """Trigger the background frame writer to terminate
        """
        self.queue.put(Terminate)


def _consume_and_write(queue, path, rowindex, df):
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
    _len = len(df)

    def writedf(row, frame, store, ri):
        now = time.time()
        i = ri.value % _len
        if ri.value > _len - 1 and i == 0:
            # write frame to disk on buffer fill
            log.debug('writing with pytables...')
            try:
                store.append('data', frame, dropna=False,
                             min_itemsize=min_size)
                store.flush(fsync=True)
            except ValueError:
                log.error(traceback.format_exc())
            log.debug("disk write took '{}'".format(time.time() - now))

        # insert by row int-index
        frame.iloc[i, :] = row
        log.debug("pandas insert took '{}'".format(time.time() - now))
        ri.value += 1  # increment row insertion index

    # use first data point
    row = queue.get()

    if row is not Terminate:
        writedf(row, df, store, rowindex)
        # infer dtypes using first row
        df = df.apply(lambda df: df.astype('object'))

        # consume and process
        for row in iter(queue.get, Terminate):
            writedf(row, df, store, rowindex)

    store.close()
    log.debug("terminating frame writer '{}'".format(proc.name))


def load(path, wrapper=pd.DataFrame):
    '''Load a pickeled numpy array from the filesystem into a `DataStorer`
    wrapper.

    WARNING: Deprecated use `from_store` to load HDF files.
    '''
    array = np.load(path)

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
    calc_rates.figspec = {
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

    return DataStorer(path, wrapper(array), metrics_func=calc_rates)


def from_store(path):
    """Load an HDF file from the into a `pandas.HDFStore`
    """
    return pd.HDFStore(path)
