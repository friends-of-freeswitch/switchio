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
from switchy import utils
import multiprocessing as mp
from multiprocessing import queues
import time


# use the entire screen width + wrapping
pd.set_option('display.expand_frame_repr', False)
# app names should generally be shorter then this...
min_size = 30


def moving_avg(x, n=100):
    '''Compute the windowed arithmetic mean of `x` with window length `n`
    '''
    n = min(x.size, n)
    cs = np.cumsum(x)
    cs[n:] = cs[n:] - cs[:-n]
    # cs[n - 1:] / n  # true means portion
    return cs / n  # NOTE: first n-2 vals are not true means


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
