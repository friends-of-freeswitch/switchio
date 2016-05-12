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
from collections import OrderedDict, deque
from contextlib import contextmanager
import tempfile
import csv
import os
import shmarray
from switchy import utils
import multiprocessing as mp
from multiprocessing import queues
import time

try:
    import pandas as pd
except ImportError:
    pd = None
else:
    # use the entire screen width + wrapping when viewing frames in the console
    pd.set_option('display.expand_frame_repr', False)


# app names should generally be shorter then this...
min_size = 30


def moving_avg(x, n=100):
    '''Compute the windowed arithmetic mean of `x` with window length `n`
    '''
    n = min(x.size, n)
    cs = pd.np.cumsum(x)
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
    return tempfile.mktemp() + '_switchy_data.{}'.format(ext)


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

    def append(self, df, key=None):
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
                store.append(df, key=path)

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
            iteritems = getattr(dtypes, 'iteritems', None)
            if iteritems:
                dtypes = iteritems()
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
            self.csvreader = csv.DictReader(
                self.csvfile, fieldnames=self.fields)
            yield self
            self.csvreader = None

    @classmethod
    @contextmanager
    def writer(cls, path, dtypes=None, mode='a'):
        existed = os.path.exists(path)
        with cls(path, dtypes=dtypes).open(mode=mode) as self:
            self.csvwriter = csv.DictWriter(
                self.csvfile, fieldnames=self.fields)

            # write a header line if no prior file existed
            if not existed and self.fields:
                self.csvwriter.writeheader()
                self._headerlen = self.bytelen()

            yield self
            self.csvwriter = None

    if pd:
        def append(self, df):
            """Append a `pd.DataFrame` to our csv file
            """
            df.to_csv(self.path, header=False, mode='a')

        def read(self):
            """Read the entire csv data set into a `pd.DataFrame`
            """
            return pd.read_csv(self.path, dtype=self.dtypes)

    else:
        def append(self, array):
            """Append an array's worth of data points to to our csv file
            """
            self.csvwriter.writerows(map(dict, array))

        def read(self):
            """Read the entire csv data set into a `list(csv.DictReader())`
            """
            return list(self.csvreader)

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
                store.append(df)

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


class DataStorer(object):
    """Receive and store row-oriented data points from switchy apps.

    A shared-memory buffer array is used to store the most recently written
    data (rows) and is flushed incrementally the to the chosen storage backend.
    """
    def __init__(self, name, dtype, data=None, buf_size=2**10, path=None,
                 storetype=None):
        self.name = name
        try:
            self.dtype = pd.np.dtype(dtype)
        except TypeError:
            # set all columns to float64
            self.dtype = pd.np.dtype(
                zip(dtype, itertools.repeat(pd.np.float64)))

        if data is None:
            # allocated a shared mem np structured array
            self._shmarr = shmarray.create(buf_size, dtype=self.dtype)
        else:
            # whatever array was passed in (eg. loaded data)
            self._shmarr = pd.np.array(data)

        self._len = len(self._shmarr)
        self.log = utils.get_logger(type(self).__name__)
        # shared current row insertion-index
        self._iput = 0
        self._ri = mp.Value('i', 0 if data is None else self._len, lock=False)

        # parent proc read-only access to disk store
        self.storetype = storetype or CSVStore
        self._storepath = path or tmpfile(self.storetype.ext)
        self.store = self.storetype(self._storepath, dtypes=self.dtype)

        if data is None:
            # setup bg writer
            self.queue = queues.Queue()
            # disable SIGINT while we spawn
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            self._writer = mp.Process(
                target=_consume_and_write,
                args=(
                    self.queue, self._storepath, self.store, self._ri,
                    self._shmarr),
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

    @property
    def buffer(self):
        """The latest set of buffered data points not yet pushed to disk
        """
        return pd.DataFrame.from_records(self._shmarr[:self.buflen])

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

    def stopwriter(self):
        """Trigger the background frame writer to terminate
        """
        self.queue.put(Terminate, timeout=3)


def _consume_and_write(queue, path, store, ri, sharr):
    """Insert :var:`row` pushed onto the queue into the shared memory array
    at the current index and increment.
    Return a boolean indicating whether the current entry
    has caused a flush to the storage backend (normally onto disk).
    Empty rows are always written to disk (keeps stores 'call-index-aligned').
    """
    proc = mp.current_process()
    slog = utils.get_logger(proc.name)
    log = mp.log_to_stderr(slog.getEffectiveLevel())
    log.info("starting storage writer '{}'".format(proc.name))
    log.info("storage path is '{}'".format(path))

    convert = pd.DataFrame.from_records if pd else None

    _len = len(sharr)

    # set up a new store instance for writing
    with store.writer(path, dtypes=store.dtypes) as store:
        queue.put(path)  # notify parent that file has been created
        # consume and process
        for row in iter(queue.get, Terminate):
            now = time.time()
            i = ri.value % _len
            if ri.value > _len - 1 and i == 0:
                # write frame to disk on buffer fill
                log.debug('writing to {} storage...'.format(store.ext))
                try:
                    store.append(convert(sharr) if convert else sharr)
                except ValueError:
                    log.error(traceback.format_exc())
                log.debug("disk write took '{}'".format(time.time() - now))
            # insert into numpy structured array by row int-index
            try:
                sharr[i] = row
                log.debug("shmarray insert took '{}'".format(
                          time.time() - now))
                # increment row insertion index for the next entry (this means
                # the last entry is at now at i - 1)
                ri.value += 1
            except ValueError:
                log.error(traceback.format_exc())

    log.debug("terminating frame writer '{}'".format(proc.name))
