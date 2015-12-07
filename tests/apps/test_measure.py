# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Measurement collection testing:
Tests for the pandas machinery
'''
import pytest
import time
from switchy.apps import players


@pytest.fixture(autouse=True)
def metrics():
    """Load the measurement sub-module as long as there are no import issues
    otherwise skip this test set.
    """
    try:
        from switchy.apps.measure import metrics
        return metrics
    except ImportError as ie:
        pytest.skip(
            "'{}' is required to run measurement tests"
            .format(ie.message.split()[-1])
        )


@pytest.mark.parametrize("length", [1, 128])
def test_buffered_datastorer(metrics, length):
    """Verify the storer's internal in-mem buffering and disk flushing logic
    """
    np = metrics.np
    ds = metrics.DataStorer(
        'test_buffered_ds',
        dtype=[('ints', np.uint32), ('strs', 'S5')],
        buf_size=length,
    )
    assert ds._writer.is_alive()
    # generate enough entries to fill up the buffer once
    for i in range(length):
        entry = (i, str(i))
        ds.append_row(entry)
        time.sleep(0.005)  # sub-proc write delay
        # in mem array entries
        assert tuple(ds._shmarr[i]) == entry
        assert tuple(ds.data.iloc[i]) == entry
        assert tuple(ds.data.iloc[-1]) == entry
        assert len(ds.data) == i + 1

    # no write uo disk yet
    assert not ds.store.keys()
    # buffer should have filled once
    assert len(ds.data) == len(ds._shmarr)

    # 1st buffer flush point
    i += 1
    entry = (i, str(i))
    ds.append_row(entry)
    time.sleep(0.03)  # flush delay
    assert ds.store.keys()
    assert all(ds.store['data'])
    # num of elements flushed to disk should be not > buffer length
    assert len(ds.store['data']) == length
    with pytest.raises(IndexError):
        ds.store['data'].iloc[length]
    # last on-disk value should be last buffer value
    assert ds.store['data'].iloc[i - 1][0] == length - 1
    # latest in buffer value should be at first index
    assert ds._shmarr[0][0] == length == i
    # combined `data` should be contiguous
    assert ds.data.iloc[i][0] == length == i

    # fill a second buffer
    x = i  # start counting from where we left off
    for _ in range(length - 1):
        x += 1
        entry = (x, str(x))
        ds.append_row(entry)

    # verify 2nd buf not yet flushed to disk
    assert len(ds.store['data']) == len(ds._shmarr)
    # last on-disk value should still be the last from the first buffer
    assert ds.store['data'].iloc[-1][0] == length - 1
    with pytest.raises(IndexError):
        ds.store['data'].iloc[length]

    # 2nd flush
    x += 1
    entry = (x, str(x))
    ds.append_row(entry)  # triggers 2nd flush
    time.sleep(0.03)  # flush delay
    assert len(ds.store['data']) == length * 2
    ilast = 2 * length - 1
    assert ds.store['data'].iloc[ilast][0] == ilast
    with pytest.raises(IndexError):
        ds.store['data'].iloc[length * 2]
    assert len(ds.data) == 2 * length + 1

    # double check all values
    for i in range(2 * length + 1):
        assert ds.data.iloc[i][0] == i


def test_no_dtypes(metrics):
    """Ensure that When no explicit dtype is provided, all row entries are cast
    to float internally.
    """
    ds = metrics.DataStorer('no_dtype', ['ones', 'twos'])
    entry = (1, 2)
    ds.append_row(entry)
    time.sleep(0.005)  # write delay
    ds.append_row(('one', 'two'))
    # ^ should have failed due to type
    assert tuple(ds.data.iloc[-1]) == entry
    ds.append_row(('1', '2'))
    # ^ should be typecast to float correctly
    assert tuple(ds.data.iloc[-1]) == entry


def test_loaded_datastorer(metrics):
    """A loaded array should work just as well
    """
    np = metrics.np
    rarr = np.random.randn(100, 4)
    ds = metrics.DataStorer('test_loaded_ds', rarr.dtype, data=rarr)
    assert not hasattr(ds, '_writer')  # no sub-proc launched
    assert ds.data.shape == rarr.shape
    assert (ds.data == rarr).all().all()


def test_write_speed(metrics):
    """Assert we can write and read quickly to the storer
    """
    np = metrics.np
    ds = metrics.DataStorer(
        'test_buffered_ds',
        dtype=[('ints', np.uint32), ('strs', 'S5')],
    )
    numentries = 3 * len(ds._shmarr)
    for i in range(numentries):
        entry = (i, str(i))
        ds.append_row(entry)
    time.sleep(0.03)  # 20ms to flush 3 bufs...
    assert len(ds.data) == numentries
    assert tuple(ds.data.iloc[-1]) == entry


def test_df_buffering_with_orig(get_orig):
    """Test that using a `DataStorer` with a single row dataframe
    stores data correctly
    """
    orig = get_orig('doggy', rate=80)
    orig.load_app(players.TonePlay)
    # configure max calls originated to length of of storer buffer
    ct_storer = orig.measurers['CallTimes'].storer
    orig.limit = orig.max_offered = ct_storer._len or 1
    assert ct_storer.bindex == 0
    orig.start()

    # wait for all calls to come up then hupall
    orig.waitwhile(lambda: orig.total_originated_sessions < orig.max_offered)
    orig.hupall()
    start = time.time()
    orig.waitwhile(
        lambda: orig.pool.count_calls() and ct_storer._iput < orig.max_offered,
        timeout=10
    )
    print("'{}' secs since all queue writes".format(time.time() - start))

    start = time.time()
    orig.waitwhile(lambda: ct_storer.rindex < orig.max_offered, timeout=10)
    print("'{}' secs since all written to frame".format(time.time() - start))

    # index is always post-incremented after each row append
    assert orig.max_offered == ct_storer.rindex
    assert not len(ct_storer.store)
    assert not ct_storer._store.keys()  # no flush to disk yet

    # verify that making one addtional call results in data being inserted
    # into the beginning of the df buffer and a flush to disk
    orig.max_offered += 1
    orig.limit = 1
    orig.start()
    time.sleep(1)
    orig.hupall()
    orig.waitwhile(lambda: ct_storer.rindex < orig.max_offered, timeout=10)
    assert ct_storer.rindex == orig.max_offered
    # post increment means 1 will be the next insertion index
    assert ct_storer.bindex == 1
    assert ct_storer.store.keys()  # flushed to disk
    assert len(ct_storer.store['data']) == orig.total_originated_sessions - 1
