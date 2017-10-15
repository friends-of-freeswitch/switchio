# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Measurement collection testing:
Tests for the pandas machinery
'''
import sys
import time
import tempfile
from functools import partial
import pytest
import switchy
from switchy.apps.measure import pd


@pytest.fixture
def measure(request):
    """Load the measurement sub-module as long as there are no import issues
    otherwise skip this test set.
    """
    from switchy.apps import measure
    return measure


@pytest.fixture(params=['CSVStore', 'HDFStore'])
def storetype(request, measure):
    """Deliver a storage type
    """
    name = request.param
    if 'HDF' in name:
        pytest.importorskip("pandas")
        pytest.importorskip("tables")
        pytest.importorskip("shmarray")
    return getattr(measure.storage, name)


@pytest.fixture
def storer(request, measure, storetype):
    """Deliver a `DataStorer` type
    """
    return partial(measure.storage.DataStorer, storetype=storetype)


@pytest.mark.skipif(
    sys.version_info >= (3,), reason="Unicode bugs on py3 with pandas"
)
@pytest.mark.skipif(not pd, reason="No pandas installed")
@pytest.mark.parametrize("length", [1, 128])
def test_buffered(measure, storer, length):
    """Verify the storer's internal in-mem buffering and disk flushing logic
    """
    ds = storer(
        'test_buffered_ds',
        dtype=[('ints', 'uint32'), ('strs', 'S5')],
        buf_size=length,
    )
    assert len(ds.data) == 0
    assert ds._writer.is_alive()
    # generate enough entries to fill up the buffer once
    for i in range(length):
        entry = (i, str(i))
        ds.append_row(entry)
        time.sleep(0.005)  # sub-proc write delay
        # in mem array entries
        assert tuple(ds._buffer._shmarr[i]) == entry
        assert tuple(ds.data.iloc[i]) == entry
        assert tuple(ds.data.iloc[-1]) == entry
        assert len(ds.data) == i + 1

    # no write uo disk yet
    assert not len(ds.store)
    # buffer should have filled once
    assert len(ds.data) == len(ds._buffer._shmarr)

    # 1st buffer flush point
    i += 1
    entry = (i, str(i))
    ds.append_row(entry)
    time.sleep(0.03)  # flush delay
    assert len(ds.store)
    assert all(ds.store.data)
    # num of elements flushed to disk should be not > buffer length
    assert len(ds.store.data) == length
    with pytest.raises(IndexError):
        ds.store.data.iloc[length]
    # last on-disk value should be last buffer value
    assert ds.store.data.iloc[i - 1][0] == length - 1
    # latest in buffer value should be at first index
    assert ds._buffer._shmarr[0][0] == length == i
    # combined `data` should be contiguous
    assert ds.data.iloc[i][0] == length == i

    # fill a second buffer
    x = i  # start counting from where we left off
    for _ in range(length - 1):
        x += 1
        entry = (x, str(x))
        ds.append_row(entry)

    # verify 2nd buf not yet flushed to disk
    assert len(ds.store.data) == len(ds._buffer._shmarr)
    # last on-disk value should still be the last from the first buffer
    assert ds.store.data.iloc[-1][0] == length - 1
    with pytest.raises(IndexError):
        ds.store.data.iloc[length]

    # 2nd flush
    x += 1
    entry = (x, str(x))
    ds.append_row(entry)  # triggers 2nd flush
    time.sleep(0.03)  # flush delay
    assert len(ds.store.data) == length * 2
    ilast = 2 * length - 1
    assert ds.store.data.iloc[ilast][0] == ilast
    with pytest.raises(IndexError):
        ds.store.data.iloc[length * 2]
    assert len(ds.data) == 2 * length + 1

    # double check all values
    for i in range(2 * length + 1):
        assert ds.data.iloc[i][0] == i


@pytest.mark.skipif(not pd, reason="No pandas installed")
def test_no_dtypes(measure, storer):
    """Ensure that When no explicit dtype is provided, all row entries are cast
    to float internally.
    """
    ds = storer('no_dtype', ['ones', 'twos'])
    entry = (1, 2)
    ds.append_row(entry)
    time.sleep(0.005)  # write delay
    ds.append_row(('one', 'two'))
    # ^ should have failed due to type
    assert tuple(ds.data.iloc[-1]) == entry
    ds.append_row(('1', '2'))
    # ^ should be typecast to float correctly
    assert tuple(ds.data.iloc[-1]) == entry


def write_bufs(
    num,
    ds,
    dtype=[('ints', 'i4'), ('strs', 'S5')],
    func=lambda i: (i, str(i)),
):
    if not isinstance(ds, switchy.apps.measure.storage.DataStorer):
        ds = ds(
            'test_buffered_ds',
            dtype=dtype,
        )
    numentries = num * ds._buf_size
    for i in range(numentries):
        entry = func(i)
        ds.append_row(entry)
    return ds


@pytest.mark.skipif(
    sys.version_info >= (3,), reason="Unicode bugs on py3 with pandas"
)
@pytest.mark.skipif(not pd, reason="No pandas installed")
def test_measurers(measure, tmpdir, storetype):
    pd = measure.storage.pd

    # an operator
    def concat(df):
        return df + df

    # a figspec for plotting only the columns with numeric types
    concat.figspec = {
        (1, 1): ['ints'],
    }

    class MeasureBuddy(object):
        fields = [('ints', 'uint32'), ('strs', 'S5')]
        storer_kwargs = {'buf_size': 10}
        operators = {'concat': concat}

    ms = measure.Measurers(storetype=storetype)

    # no prepost method defined
    with pytest.raises(AttributeError):
        name = ms.add(MeasureBuddy)

    # add a prepost method which is missing a `storer` kwarg
    def prepost(self):
        pass

    MeasureBuddy.prepost = prepost.__get__(ms, MeasureBuddy)  # make a method
    with pytest.raises(TypeError):
        name = ms.add(MeasureBuddy)

    # add a prepost method which accepts a `storer` kwarg
    def prepost(self, storer=None):
        self.storer = storer

    MeasureBuddy.prepost = prepost.__get__(ms, MeasureBuddy)
    name = ms.add(MeasureBuddy)

    # verify container
    assert name in ms
    m = ms[name]  # get measurer
    assert len(ms.items()) == 1

    # verify operator
    assert 'concat' in ms._ops
    assert concat is m.ops['concat']
    assert 'concat' in ms.ops

    # verify figspec
    assert concat.figspec == ms.figspecs.concat

    # write 3 bufs worth
    ds = write_bufs(3, ds=m.storer)
    # check storer
    assert name in ms.stores
    assert m.storer is ds
    assert ds is ms._stores[name]
    time.sleep(0.05)
    assert len(ms.ops.concat) == len(m.storer.data) == len(ds.data)
    # check merged
    assert (ms.ops.concat == ms.merged_ops).all().all()

    # check offline storage
    with pytest.raises(ValueError):
        # must be a dir path
        pklpath = ms.to_store(tempfile.mktemp())

    pklpath = ms.to_store(tempfile.mkdtemp())
    merged = pd.concat([ds.data, ms.ops.concat], axis=1)
    df = measure.load(pklpath, dtypes=merged.dtypes)

    # verify aggregated frames
    assert len(df) == len(ds.data)
    assert (df.dtypes == merged.dtypes).all()
    assert (df == merged).all().all()

    # double check figspec / partial func
    assert df._plot.args[1] == concat.figspec
    # ensure plotting doesn't throw errors
    figpath = tmpdir.join('switchy_figure.png')
    assert df._plot(fname=str(figpath))
    assert figpath.exists()


def test_write_speed(measure, storer, travis):
    """Assert we can write and read "quickly" to the storer
    """
    sleeptime = 0.1
    if travis:
        sleeptime += 0.1

    ds = write_bufs(3, ds=storer)
    numentries = 3 * ds._buf_size
    time.sleep(sleeptime)  # wait to flush 3 bufs...
    assert len(ds.data) == numentries
    if measure.storage.pd:
        assert len(ds._buffer) == ds._buf_size


def test_with_orig(get_orig, measure, storer):
    """Test that using a `DataStorer` with a single row dataframe
    stores data correctly
    """
    from switchy.apps import players
    pd = measure.pd
    orig = get_orig('doggy', rate=100)
    orig.load_app(players.TonePlay)

    # configure max calls originated to length of of storer buffer
    cdr_storer = orig.measurers['CDR'].storer
    assert len(cdr_storer.data) == 0
    orig.limit = orig.max_offered = cdr_storer._buf_size or 1
    # orig.limit = orig.max_offered = 1
    if pd:
        assert cdr_storer._buffer.bi == 0

    orig.start()

    # wait for all calls to come up then hupall
    orig.waitwhile(lambda: orig.total_originated_sessions < orig.max_offered)
    orig.hupall()
    start = time.time()
    orig.waitwhile(
        lambda:
            orig.pool.count_calls() and cdr_storer._iput < orig.max_offered,
        timeout=10
    )
    print("'{}' secs since all queue writes".format(time.time() - start))

    start = time.time()
    orig.waitwhile(
        lambda: len(cdr_storer.data) < orig.max_offered, timeout=10)
    print("'{}' secs since all written to frame".format(time.time() - start))

    # index is always post-incremented after each row append
    # (WARNING: the below checks may intermittently vary due to thread raciness
    # when determining if max_offered has been surpassed in an event callback)
    if pd:
        if orig.total_originated_sessions <= orig.max_offered:
            assert not len(cdr_storer.store)  # no flush to disk yet
            # verify that making one addtional call results in data being
            # inserted into the beginning of the buffer and a flush to disk
            orig.max_offered += 1
            orig.limit = 1
            orig.start()
            time.sleep(1)
            orig.hupall()
            orig.waitwhile(
                lambda: len(cdr_storer.data) < orig.max_offered, timeout=10)

            assert cdr_storer._buffer.ri.value == orig.max_offered
            # post increment means 1 will be the next insertion index
            assert cdr_storer._buffer.bi == 1

        assert len(cdr_storer.store) == cdr_storer._buf_size
        # one or more rows should be in the buffer while the rest is in the
        # store
        assert len(cdr_storer.store) <= orig.total_originated_sessions - 1

    assert len(cdr_storer.store)  # flushed to disk

    # allow for out-of-thread flush to disk
    start = time.time()
    while time.time() - start < 3:
        if len(cdr_storer.data) == orig.total_originated_sessions:
            break  # yey
        time.sleep(0.5)
    else:
        len(cdr_storer.data) == orig.total_originated_sessions
