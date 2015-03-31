# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This module includes helpers for capturing measurements using numpy.
"""
import numpy as np
from switchy import utils
from mpl_helpers import plot


# numpy ndarray template
metric_dtype = np.dtype([
    ('time', np.float32),
    ('invite_latency', np.float32),
    ('answer_latency', np.float32),
    ('call_setup_latency', np.float32),
    ('originate_latency', np.float32),
    ('num_failed_calls', np.uint16),
    ('num_sessions', np.uint16),
])


class CappedArray(object):
    """Numpy buffer with a capped length which rolls over to the beginning
    when data is inserted past the end of the internal np array.

    Wraps the numpy array as if it was subclassed by overloading the
    getattr iterface
    """
    def __init__(self, buf, mi):
        self._buf = buf
        self._mi = mi  # current row insertion-index
        # provide subscript access to the underlying buffer
        for attr in ('__getitem__', '__setitem__'):
            setattr(self.__class__, attr, getattr(buf, attr))

    def __dir__(self):
        attrs = utils.dirinfo(self)
        attrs.extend(self._buf.dtype.names)
        attrs.extend(dir(self._buf))
        return attrs

    def __repr__(self):
        return repr(self._buf[:self._mi])

    def __getattr__(self, name):
        """Try to return a view into the numpy buffer
        """
        try:
            # present the columns arrays as attributes
            return self._buf[:self._mi][name]
        except ValueError:  # not one of the field names
            return getattr(self._buf[:self._mi], name)

    def insert(self, value):
        '''
        Insert value(s) at the current index into the internal
        numpy array.  If value is a tuple which fills every coloumn in the
        current row of the internal buffer array then self.increment is called
        automatically.

        Parameters
        ----------
        value : type(self._buf.dtype[name]) or tuple
            value to insert
        '''
        # NOTE: consider using ndarray.itemset if we want to
        # insert into only one column?
        i = self._mi % self._buf.size
        self._buf[i] = value
        self._mi += 1
        if self._mi > self._buf.size - 1 and i == 0:
            return True
        return False


class CallMetrics(CappedArray):
    def seizure_fail_rate(self, start=0, end=-1):
        '''Compute and return the average failed call rate between
        indices `start` and `end` using the following formula:

        sfr =   nfc[end] - nfc[start]
               -----------------------
                    end - start
        where:
            nfc        ::= number of failed calls array
            start, end ::= array indices representing seizure index

        The assumption is that nfc is a strictly
        monotonic linear sequence.

        TODO:
            for non linear failed call counts we need to look at
            taking a discrete derivative...
        '''
        array = self.num_failed_calls
        if end < 0:
            end = array.size + end
        num = float(array[end] - array[start])
        denom = float(end - start)
        return num / denom

    sfr = seizure_fail_rate

    def answer_seizure_ratio(self, start=0, end=-1):
        '''
        Compute the answer seizure ratio using the following formula:

        asr = 1 - sfr

        where:
            sfr ::= seizure fail rate
        '''
        return 1. - self.seizure_fail_rate(start, end)

    asr = answer_seizure_ratio

    def plot(self):
        self.mng, self.fig, self.artists = plot(self, field_opts={
            'time': None,  # indicates this field will not be plotted
            # latencies
            'invite_latency': (1, 1),
            'answer_latency': (1, 1),
            'call_setup_latency': (1, 1),
            'originate_latency': (1, 1),
            # counts
            'num_failed_calls': (2, 1),
            # TODO: change name to num_seizures?
            'num_sessions': (2, 1)
        })


def new_array(dtype=metric_dtype, size=2**20):
    """Return a new capped numpy array
    """
    return CallMetrics(np.zeros(size, dtype=dtype), 0)


def load(path, wrapper=CallMetrics):
    '''Load a pickeled numpy array from the filesystem into a metrics wrapper
    '''
    array = np.load(path)
    return wrapper(array, array.size)


def load_from_dir(path='./*.pkl'):
    '''Autoload all pickeled arrays in a dir into Metric
    instances and plot

    Parameters
    ----------
    path : string, optional
        file system path + glob pattern to scan for files
    '''
    import glob
    file_names = glob.glob(path)
    tups = []
    for f in file_names:
        tup = plot(load(f))
        tups.append(tup)
    return tups
