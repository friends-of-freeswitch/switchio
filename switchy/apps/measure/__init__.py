# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os
import pickle
from functools import partial
from collections import OrderedDict, namedtuple
from switchy import utils
from .storage import DataStorer, get_storetype
import pandas as pd

# re-export(s)
from cdr import CDR


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
    def __init__(self, storetype=None):
        self._apps = OrderedDict()
        self.storetype = storetype
        # delegate to `_apps` for subscript access
        for meth in '__getitem__ __contains__'.split():
            setattr(self.__class__, meth, getattr(self._apps, meth))

        # add attr access for references to data frame operators
        self._ops = OrderedDict()
        self.ops = utils.DictProxy(self._ops)
        # do the same for data stores
        self._stores = OrderedDict()
        self.stores = utils.DictProxy(self._stores)
        # same for figspecs
        self._figspecs = OrderedDict()
        self.figspecs = utils.DictProxy(self._figspecs)

    def __repr__(self):
        return repr(self._apps).replace(
            type(self._apps).__name__, type(self).__name__)

    def add(self, app, name=None, operators={}, **kwargs):
        name = name or utils.get_name(app)
        prepost = getattr(app, 'prepost', None)
        if not prepost:
            raise AttributeError(
                "'{}' must define a `prepost` method".format(name))
        args, ppkwargs = utils.get_args(app.prepost)
        if 'storer' not in ppkwargs:
            raise TypeError("'{}' must define a 'storer' kwarg"
                            .format(app.prepost))
        ppkwargs = {key: kwargs.pop(key) for key in ppkwargs if key in kwargs}

        # acquire storer factory
        factory = getattr(app, 'new_storer', None)
        storer_kwargs = getattr(app, 'storer_kwargs', {})
        storer_kwargs.update(kwargs)
        storer_kwargs.setdefault('storetype', self.storetype)
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
        """Dump all data + operator combinations to a backend storage format
        on disk.
        """
        if not os.path.isdir(dirpath):
            raise ValueError("You must provide a directory")

        iterapps = self._apps.iteritems()
        # infer storage backend from first store
        name, m = next(iterapps)
        storetype = m.storer.storetype
        storepath = os.path.join(dirpath, "switchy_measures")

        framedict = OrderedDict()
        # raw data sets
        for name, m in self._apps.items():
            data = m.storer.data
            if len(data):
                framedict[name] = data

                # processed (metrics) data sets
                for opname, op in m.ops.items():
                    framedict[os.path.join(name, opname)] = op(data)

        storepath = storetype.multiwrite(storepath, framedict.items())
        # dump pickle file containing figspec (and possibly other meta-data)
        pklpath = os.path.join(dirpath, 'switchy_measures.pkl')
        with open(pklpath, 'w') as pklfile:
            pickle.dump(
                {'storepath': storepath, 'figspecs': self._figspecs,
                 'storetype': storetype.ext},
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


def load(path, **kwargs):
    """Load a previously pickled data set from the filesystem and return it as
    a merged data frame
    """
    with open(path, 'r') as pkl:
        obj = pickle.load(pkl)
        if not isinstance(obj, dict):
            return load_legacy(obj)

        # attempt to find the hdf file
        storepath = obj['storepath']
        if not os.path.exists(storepath):
            # it might be a sibling file
            storepath = os.path.basename(storepath)
            assert os.path.exists(storepath), "Can't find data store path?"

        # XXX should be removed once we don't have any more legacy hdf5
        # data sets to worry about
        storetype = get_storetype(obj.get('storetype', 'hdf5'))

        merged = storetype.multiread(storepath, **kwargs)

        # XXX evetually we should support multiple figures
        figspecs = obj.get('figspecs', {})
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
