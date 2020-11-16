# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This module includes helpers for capturing and storing measurement data.
"""
import traceback
import signal
import atexit
import itertools
from collections import OrderedDict, deque
from contextlib import contextmanager
import tempfile
import csv
import numpy
import os
from switchio import utils
import multiprocessing as mp
import time

try:
    import pandas as pd
except ImportError as ie:
    utils.log_to_stderr().warning(str(ie))
    pd = None
else:
    from . import shmarray
    # use the entire screen width + wrapping when viewing frames in the console
    pd.set_option('display.expand_frame_repr', False)


# app names should generally be shorter then this...
min_size = 30


def moving_avg(x, n=100):
    '''Compute the windowed arithmetic mean of `x` with window length `n`
    '''
    n = min(x.size, n)
    cs = numpy.cumsum(x)
    cs[n:] = cs[n:] - cs[:-n]
    # cs[n - 1:] / n  # true means portion
    return cs / n  # NOTE: first n-2 vals are not true means


_storetypes = {}


def store(cls):
    _storetypes[cls.ext] = cls
    return cls


def get_storetype(ext):
    return _storetypes[ext]


def tmpfile(ext):
    return tempfile.mktemp() + '_switchio_data.{}'.format(ext)


class Terminate(Exception):
    """"A unique error type to trigger writer proc termination
    """


@store
class HDFStore(object):
    """HDF5 storage.
    Wraps a `pandas.HDFStore` for use with multiple processes.
    """
    key = 'data'  # table key
    # app names should generally be shorter then this...
    min_size = 30
    ext = 'hdf5'

    def __init__(self, path, dtypes=None):
        self.path = path
        self.dtypes = dtypes
        self._store = pd.HDFStore(path=path, mode='a')
        self._store.close()

    @classmethod
    @contextmanager
    def reader(cls, path, dtypes=None):
        with cls(path).open(mode='r') as store:
            yield store

    @classmethod
    @contextmanager
    def writer(cls, path, dtypes=None, mode='a'):
        with cls(path).open(mode=mode) as store:
            yield store

    @contextmanager
    def open(self, mode='r'):
        self._store.open(mode=mode)
        yield self
        self._store.close()

    def put(self, df, key=None):
        """Write a `pd.DataFrame` to disk by appending it to the HDF table.
        Note: the store must already have been opened by the caller.
        """
        self._store.append(
            key or self.key,
            df,
            dropna=False,
            min_itemsize=self.min_size,
        )
        self._store.flush(fsync=True)

    def read(self):
        with self.open():
            return self._store[self.key]

    @property
    def data(self):
        return self.read()

    def __len__(self):
        with self.open():
            return len(self._store.keys())

    @classmethod
    def multiwrite(cls, storepath, dfitems):
        """"Store all data frames (from `dfitems`) in a single hdf5 file.
        """
        with cls.writer("{}.{}".format(storepath, cls.ext)) as store:
            for path, df in dfitems:
                store.put(df, key=path)

            return store.path

    @classmethod
    def multiread(cls, storepath, dtypes=None):
        with cls.reader(storepath) as store:
            store = store._store
            return pd.concat(
                (store[key] for key in store.keys()),
                axis=1,
            )


@store
class CSVStore(object):
    """CSV storage.
    """
    ext = 'csv'

    def __init__(self, path, dtypes=None):
        self.path = path

        # check for a literal numpy dtype
        dtypes = getattr(dtypes, 'descr', dtypes)

        if dtypes is not None and iter(dtypes):
            # handle pandas `DataFrame.dtypes`
            items = getattr(dtypes, 'iteritems', None)
            if items:
                dtypes = items()
            self.dtypes = OrderedDict(dtypes)
            self.fields = self.dtypes.keys()
        else:
            self.dtypes = self.fields = dtypes

        self._ondisk = False
        self.csvfile = self.csvreader = self.csvwriter = None

        if not os.path.exists(path):
            self._headerlen = 0
        else:
            with self.open():
                self._headerlen = self.bytelen()

    def bytelen(self):
        """Report the current length bytes written to disk
        """
        self.csvfile.seek(0, 2)
        return self.csvfile.tell()

    def ondisk(self):
        if not self._ondisk:
            try:
                with self.open():
                    self._ondisk = bool(self.bytelen() > self._headerlen)
                return self._ondisk
            except IOError:
                return False
        return True

    @contextmanager
    def open(self, mode='r', path=None):
        with open(path or self.path, mode=mode) as csvfile:
            self.csvfile = csvfile
            yield self
            self.csvfile = None

    @classmethod
    @contextmanager
    def reader(cls, path, dtypes=None):
        with cls(path, dtypes=dtypes).open() as self:
            self.csvreader = csv.reader(self.csvfile)
            yield self
            self.csvreader = None

    @classmethod
    @contextmanager
    def writer(cls, path, dtypes=None, mode='a'):
        existed = os.path.exists(path)
        with cls(path, dtypes=dtypes).open(mode=mode) as self:
            self.csvwriter = csv.writer(self.csvfile)

            # write a header line if no prior file existed
            if not existed and self.fields:
                self.csvwriter.writerow(self.fields)
                self._headerlen = self.bytelen()

            yield self
            self.csvwriter = None

    if pd:
        def put(self, df):
            """Append a `pd.DataFrame` to our csv file
            """
            df.to_csv(self.path, header=False, mode='a')

        def read(self):
            """Read the entire csv data set into a `pd.DataFrame`
            """
            return pd.read_csv(self.path, dtype=self.dtypes)

    else:
        def put(self, row):
            """Append an array's worth of data points to to our csv file.
            Note: this store must be opened as a writer prior to using this
            method.
            """
            self.csvwriter.writerow(row)
            self.csvfile.flush()

        def read(self):
            """Read the entire csv data set into a list of lists (the rows).
            """
            with self.reader(self.path, dtypes=self.dtypes) as store:
                return list(store.csvreader)

    @property
    def data(self):
        return self.read()

    def __len__(self):
        return len(self.read()) if self.ondisk() else 0

    @classmethod
    def multiwrite(cls, storepath, dfitems):
        os.makedirs(os.path.dirname(storepath + '/'))  # make a subdir
        for path, df in dfitems:
            filename = '{}.{}'.format(path.replace('/', '-'), cls.ext)
            filepath = os.path.join(storepath, filename)
            with cls.writer(filepath, dtypes=df.dtypes) as store:
                store.put(df)

        return storepath

    @classmethod
    def multiread(cls, storepath, dtypes=None):
        files = deque()
        for dirpath, dirnames, filenames in os.walk(storepath):
            for csvfile in filter(lambda name: cls.ext in name, filenames):
                fullpath = os.path.join(dirpath, csvfile)

                # sort frames by placing the operator data sets at the end
                if '-' in csvfile:
                    files.append(fullpath)
                else:
                    files.appendleft(fullpath)

        frames = []
        for path in files:
            with cls.reader(path, dtypes=dtypes) as store:
                frames.append(store.read())

        return pd.concat(frames, axis=1) if pd else frames


class RingBuffer(object):
    """A circular buffer interface to a shared `numpy` array
    """
    def __init__(self, dtype, size=2**10):
        # allocated a shared mem np structured array
        self._shmarr = shmarray.create(size, dtype=dtype)
        self._len = len(self._shmarr)

        # shared current absolute row insertion-index
        self.ri = mp.Value('i', 0, lock=False)

    def put(self, row):
        bi = self.bi
        # increment row insertion index for the next entry (this means
        # the last entry is at now at i - 1)
        self.ri.value += 1
        try:
            self._shmarr[bi] = row
        except ValueError:
            # XXX should never happen during production (since it's
            # means the dtype has been setup wrong)
            self.ri.value -= 1

    def read(self):
        """Return the contents of the FIFO array without incrementing the
        start index.
        """
        return self._shmarr[:len(self)]

    @property
    def df(self):
        """The buffer's current contents as a `pd.DataFrame`.
        """
        return pd.DataFrame.from_records(self.read())

    def __len__(self):
        """Current array length up the last inserted data point
        """
        bi = self.bi
        ri = self.ri
        l = self._len
        if not bi:
            # handles the 1 % 1 == 0 case when l == 1
            return bi if ri.value < l else l
        return bi

    @property
    def bi(self):
        """Current insertion index of in mem frame buffer
        (i.e. the index where the next value should be inserted)
        """
        return self.ri.value % self._len

    def is_full(self):
        return self.bi == 0 and self.ri.value > self._len - 1


class DataStorer(object):
    """Receive and store row-oriented data points from switchio apps.

    A shared-memory buffer array is used to store the most recently written
    data (rows) and is flushed incrementally the to the chosen storage backend.
    """
    def __init__(self, name, dtype, buf_size=2**10, path=None,
                 storetype=None):
        self.name = name
        try:
            self.dtype = numpy.dtype(dtype) if pd else dtype
        except TypeError:
            # set all columns to float64
            self.dtype = numpy.dtype(
                list(zip(dtype, itertools.repeat('float64')))
            )

        self.log = utils.get_logger(type(self).__name__)

        # allocated a shared mem np structured array
        self._buf_size = buf_size  # purely for testing
        self._buffer = RingBuffer(
            dtype=self.dtype, size=buf_size) if pd else None

        # parent proc read-only access to disk store
        self.storetype = storetype or CSVStore
        self._storepath = path or tmpfile(self.storetype.ext)
        self.store = self.storetype(self._storepath, dtypes=self.dtype)

        self.queue = mp.Queue()
        self._iput = 0  # queue put counter

        # disable SIGINT while we spawn
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        # setup bg writer
        self._writer = mp.Process(
            target=_consume_and_write,
            args=(
                self.queue, self._storepath, self.store, self._buffer),
            name='{}_frame_writer'.format(self.name),
        )
        self._writer.start()
        # re-enable SIGINT
        signal.signal(signal.SIGINT, signal.default_int_handler)
        # kill subproc on exit
        atexit.register(self.stopwriter)

        # ensure writer is initialized
        path = self.queue.get(timeout=3)
        assert path == self._storepath

    if pd:
        @property
        def buffer(self):
            """The latest set of buffered data points not yet pushed to disk
            """
            return self._buffer.df

        @property
        def data(self):
            """Copy of the entire data set recorded thus far
            """
            if self.store:
                return pd.concat(
                    (self.store.data, self.buffer),
                    ignore_index=True
                )
            return self.buffer
    else:
        @property
        def data(self):
            """Copy of the data points recorded thus far
            """
            with self.store.reader(
                self.store.path, dtypes=self.dtype
            ) as reader:
                return reader.data[1:]

    def append_row(self, row=None):
        """Push a row of data onto the consumer queue
        """
        start = time.time()
        self.queue.put(row)
        self._iput += 1
        diff = time.time() - start
        if diff > 0.005:  # any more then 5ms warn the user
            self.log.warning("queue.put took '{}' seconds".format(diff))

    def stopwriter(self):
        """Trigger the background frame writer to terminate
        """
        self.queue.put(Terminate, timeout=3)


def _consume_and_write(queue, path, store, sharr):
    """Insert :var:`row` received from the queue into the shared memory array
    at the current index and increment. Empty rows are always written to disk
    (keeps stores 'call-index-aligned').
    """
    proc = mp.current_process()
    slog = utils.get_logger(proc.name)
    log = mp.log_to_stderr(slog.getEffectiveLevel())
    log.debug("starting storage writer '{}'".format(proc.name))
    log.info("storage path is '{}'".format(path))
    log.debug("sharr is '{}'".format(sharr))

    # set up a new store instance for writing
    with store.writer(path, dtypes=store.dtypes) as store:
        # notify parent that file has been created
        queue.put(path)

        # handle no pandas/np case
        buff = store if sharr is None else sharr
        bufftype = type(buff)
        log.debug('buffer type is {}'.format(bufftype))

        for row in iter(queue.get, Terminate):  # consume and process
            now = time.time()

            # write frame to disk on buffer fill
            if sharr and sharr.is_full():
                log.debug('writing to {} storage...'.format(store.ext))
                try:
                    # push a data frame
                    store.put(pd.DataFrame.from_records(buff.read()))
                except ValueError:
                    log.error(traceback.format_exc())
                log.debug("storage put took '{}'".format(time.time() - now))

            try:  # push to ring buffer (or store if no pd)
                buff.put(row)
                log.debug("{} insert took '{}'".format(
                          bufftype, time.time() - now))
            except ValueError:
                log.error(traceback.format_exc())

    log.debug("terminating frame writer '{}'".format(proc.name))
