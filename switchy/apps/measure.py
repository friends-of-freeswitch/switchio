"""
Measurements app for collecting call latency and performance stats.

This module includes helper classes for taking load measurements using numpy.
"""
import logging
import weakref
from ..marks import event_callback
from .. import utils
import numpy as np
import glob
import os
from collections import OrderedDict, defaultdict


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
    def __init__(self, buf):
        self._buf = buf
        self._mi = 0  # current row insertion-index
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


def new_array(dtype=metric_dtype, size=2**20):
    """Return a new capped numpy array
    """
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

    return CallMetrics(np.zeros(size, dtype=dtype))


class Metrics(object):
    """Collect call oriented measurements

    Only an instance of this class can be loaded as switchy app
    """
    def __init__(self, listener=None, array=None):
        self.listener = weakref.proxy(listener) if listener else listener
        self.log = utils.get_logger(__name__)
        self._array = array if array else new_array()  # np default buffer

    def prepost(self, listener, array=None):
        if array is not None:
            # array can be overriden at app load time
            self._array = array
        self.listener = listener
        yield
        del self.listener

    @property
    def array(self):
        return self._array

    @event_callback('CHANNEL_HANGUP')
    def log_stats(self, sess, job):
        """Append measurement data inserting only once per call
        """
        # TODO: eventually we should use a data type which allows the
        # separation of metrics between those that require two vs. one
        # leg to calculate?
        l = self.listener
        if sess.call.sessions:
            # the `callee` UA is who's time measures we want
            partner_sess = sess.call.sessions[-1]
            if l.sessions.get(partner_sess.uuid, False):
                rollover = self._array.insert((
                    sess.create_time - l._epoch if l else sess.create_time,
                    abs(sess.create_time - partner_sess.create_time),
                    abs(sess.answer_time - partner_sess.answer_time),
                    abs(sess.answer_time - sess.create_time),
                    sess.originate_time - job.launch_time if job else 0,
                    l.total_failed_sessions if l else 0,
                    sess.num_sessions,
                ))
                if rollover:
                    self.log.warn('resetting metric buffer index!')
