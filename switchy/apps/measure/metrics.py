# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This module includes helpers for capturing measurements using pandas.
"""
import threading
from Queue import Queue
import tempfile
import pandas as pd
import numpy as np
from switchy import utils
from functools import partial
from collections import OrderedDict, namedtuple
import time

# use the entire screen width + wrapping
pd.set_option('display.expand_frame_repr', False)


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


class FrameFuncOp(object):
    def __init__(self, storersdict, func):
        self._sd = storersdict
        self._func = func
        setattr(self.__class__, '__getitem__',
                getattr(self._sd, '__getitem__'))

    def __get__(self, obj, type=None):
        """Return the merged set when accessed as an instance var
        """
        return self.merged

    def __set__(self, obj, value):
        raise AttributeError

    def __repr__(self):
        return repr(self._sd).replace(
            type(self._sd).__name__, type(self).__name__)

    def __call__(self, *args, **kwargs):
        return self._func(*args, **kwargs)

    def __dir__(self):
        return utils.dirinfo(self) + self._sd.keys()

    def __getattr__(self, key):
        """Given a key to a storer (usually a call app name)
        apply the dataframe operator function over the entire data set
        """
        return self._func(self._sd[key].data)

    def get_merged(self, names=None):
        """Merge multiple storer datas into a single frame
        """
        if names:
            storers = (
                storer for name, storer in
                self._sd.items() if name in names
            )
        else:
            storers = self._sd.values()

        # XXX this won't work for multiple stores with non-unique column names
        # Consider having this return a MultiIndexed df eventually?
        return pd.concat(
            map(self._func, (s.data for s in storers)),
            axis=1,
        )

    merged = property(get_merged)


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

        # acquire storer factory
        factory = getattr(app, 'new_storer', None)
        if not factory:
            # app does not define a storer factory method
            factory = partial(DataStorer, columns=app.fields)
        # create an instance
        storer = factory()

        name = name or utils.get_name(app)
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
        fo = FrameFuncOp({measurername: m.storer}, func)
        self._ops[opname] = fo
        figspec = getattr(func, 'figspec', None)
        if figspec:
            self._figspecs[opname] = figspec
        # provides descriptor protocol access for interactive work
        setattr(self.ops.__class__, opname, fo)

    def items(self):
        return list(reversed(self._apps.items()))

    def to_store(self, path):
        """Dump all data + operator combinations to a hierarchical HDF store
        on disk.
        """
        with pd.HDFStore(path) as store:
            # append raw data sets
            for name, m in self._apps.items():
                data = m.storer.data
                if len(data):
                    store.append("{}".format(name), data)

                    # append processed (metrics) data sets
                    for opname, op in m.ops.items():
                        store.append(
                            '{}/{}'.format(name, opname),
                            op(data),
                            dropna=False,
                        )

    @property
    def merged_ops(self):
        """Merge and return all function operator frames from all measurers
        """
        return pd.concat(
            (opfunc.merged for opfunc in self._ops.values()),
            axis=1,  # concat along the columns
        )

    def plot(self, **kwargs):
        """Plot all figures specified in the `figspecs` dict.
        """
        return [
            (figspec, plot_df(self.merged_ops, figspec, **kwargs))
            for figspec in self._figspecs.values()
        ]


class DataStorer(object):
    """Wraps a `pd.DataFrame` which buffers recent data in memory and
    offloads excess to disk using the HDF5 format.
    """
    class Terminate(object):
        "A unique type to trigger writer thread terminatation"

    def __init__(self, data=None, columns=None, size=2**10,
                 dtype=None, hdf_path=None):

        self.queue = Queue()
        self._writer = threading.Thread(
            target=self._writedf,
            args=(),
            name='frame_writer'
        )
        self._writer.daemon = True  # die with parent
        self._writer.start()
        self._df = pd.DataFrame(
            data=data,
            columns=columns,
            index=range(size) if data is None else None,
            dtype=dtype,
        )
        self._len = len(self._df)
        # current row insertion-index
        self._ri = 0 if data is None else len(self._df) - 1
        # disk storage is normally
        self._store = pd.HDFStore(
            hdf_path or tempfile.mktemp() + '_switchy_data.h5'
        )
        self._store.open('a')
        self.log = utils.get_logger(type(self).__name__)

    def __len__(self):
        return len(self._df)

    @property
    def store(self):
        """HDF5 Store for offloading data to disk
        """
        return self._store

    @property
    def buffer(self):
        """The latest set of buffered data points not yet pushed to disk
        """
        return self._df[:self.findex].convert_objects()

    @property
    def data(self):
        """Copy of the entire data set recorded thus far
        """
        if self._store.keys():
            return pd.concat(
                (self._store['data'], self.buffer),
                ignore_index=True
            )
        return self.buffer

    @property
    def index(self):
        '''Current absolute row index
        '''
        return self._ri

    @property
    def findex(self):
        """Current index of in mem frame buffer
        """
        return self._ri % self._len

    def append_row(self, row=None):
        # PyTables store is not thread safe so push a row
        self.queue.put(row)

    def stop(self):
        """Trigger the background writer thread to terminate
        """
        self.queue.put(self.Terminate)

    def _writedf(self):
        '''Insert :var:`row` pushed onto the queue into the internal data
        frame at the current index and increment.
        Return a boolean indicating whether the current entry
        has caused a flush to disk. Empty rows are always written to disk
        (keeps stores 'call-index-aligned').
        '''
        for row in iter(self.queue.get, self.Terminate):
            i = self.findex
            now = time.time()
            if self._ri > self._len - 1 and i == 0:
                # write frame to disk
                self._df = frame = self._df.convert_objects(
                    convert_numeric=True)
                self._store.append('data', frame, dropna=False)
                self._store.flush(fsync=True)
                self.log.info("disk write took '{}'".format(time.time() - now))

            # insert by row int-index
            self._df.iloc[i, :] = row
            self._ri += 1
            self.log.debug("pandas insert took '{}'".format(time.time() - now))

        self.log.debug("terminating writer thread")


def load(path, wrapper=pd.DataFrame):
    '''Load a pickeled numpy array from the filesystem into a `DataStorer`
    wrapper (Deprecated use `from_store` to load HDF files).
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

    ds = DataStorer(wrapper(array), metrics_func=calc_rates)
    return ds


def from_store(path):
    """Load an HDF file from the into a `pandas.HDFStore`
    """
    return pd.HDFStore(path)
