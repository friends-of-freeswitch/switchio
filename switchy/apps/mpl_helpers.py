# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Measurement and plotting tools - numpy + mpl helpers
"""
# TODO:
#     - figure.tight_layout doesn't seem to work??
#     - make legend malleable
# reject - consider making a heuristic that if an array's range is within
#          an order of mag of some other, they are both placed on the same
#          axes?
#     - consider placing arrays on the same axes which have the same suffix?
#     - consider a way to easily move lines to different axes and re-rendering
#       leveraging ipython tab completion
import matplotlib.pyplot as plt


class OverwriteError(Exception):
    pass


class Plotter(object):
    '''
    A container for collecting measurements and storing them in a multi-field
    numpy array.

    Parameters
    ----------
    buf : ndarray or string, optional
        Optional numpy array to hold measurements or path string to pickled
        np array
    length : int, optional
        Optional length of internal buffer Only usefule if buf or file_name is
        not provided
    '''
    field_sig = OrderedDict()
    # mpl font settings
    font_style = {'size': 'small'}

    def __init__(self, buf=None, length=2**20, title='Metrics'):

        self._mi = 0  # current metric insertion-index
        self._init = False
        self._save_num = 1

        # mpl bindings
        self._fig = None
        self._mng = None
        self._axes = bunch.Bunch()
        self._plot_opts = defaultdict(dict)
        self.fields = OrderedDict()

        # parse args
        if buf is None:
            self._buf = buf
            # create an new internal buffer
            self.length = length
            # add any records declared in the class defn
            for name, opts in self.field_sig.items():
                dtype = opts.get('dtype')
                self.add_measure(name, data_type=dtype, **opts)
        elif buf is not None:
            # we're handed either an array or a file path
            if isinstance(buf, str):
                self._buf = np.load(buf)
                filename = os.path.basename(buf)
                self._title, ext = os.path.splitext(filename)
            else:
                self._buf = buf
            self.length = self._buf.size
            self._mi = self.length
            fields = self._buf.dtype.fields

            # add fields in a 'suffix sorted' order
            for name in sorted(fields.keys(),
                               key=lambda name: name.rsplit('_')[-1:]):
                type_tup = fields[name]
                dtype = type_tup[0]  # dtype is 1st in tuple
                self.add_measure(name, data_type=dtype)

            # validate field signature declared in the class declaration
            for name, opts in self.field_sig.items():
                assert self._buf[name].any(), ("Field signature mismatch '{}'!"
                                               .format(name))
                assert self.fields[name] == opts['dtype'], \
                    "Field type mismatch '"+name+"'!"
                self.edit_measure(name, **opts)
            self._init = True

    def __dir__(self):
        attrs = dir(self.__class__)
        attrs.extend(self.__dict__)
        if self._buf is not None:
            attrs.extend(self._buf.dtype.names)
            attrs.extend(dir(self._buf))
        return attrs

    def __repr__(self):
        inst_repr = object.__repr__(self).rstrip('>')
        fields_repr = " with fields '" + "', '".join(self.fields)\
            if len(self.fields) else ''
        return inst_repr + fields_repr + "'>"

    def __getattr__(self, name):
        try:
            return getattr(self._buf, name)
        except AttributeError:
            return object.__getattribute__(self, name)

    def add_measure(self, name, data_type=np.float32, **plot_opts):
        if self._init:
            raise OverwriteError("Metric has already been initialized;"
                                 " clear first")
        self.fields[name] = data_type
        self._plot_opts[name].update(plot_opts)

    def edit_measure(self, name, dtype=None, **plot_opts):
        if dtype is not None:
            self.fields[name] = dtype
        self._plot_opts[name].update(**plot_opts)

    def setup(self):
        '''
        Init the internal numpy array/records for use
        '''
        if self._init:
            raise OverwriteError("You must reset this metric set before"
                                 " re-initializing!")
        # build np dtype and array
        self._dtype = np.dtype(self.fields.items())
        self._buf = np.zeros(self.length, dtype=self._dtype)
        self._mi = 0
        self._init = True  # mark us an initialized

    def get_title(self):
        return self._title

    def set_title(self, name):
        self._title = name
        if not self._mng:
            self.get_fig()  # activate fig creation
        self._mng.window.set_title(name)

    title = property(get_title, set_title, "Title of this metrics instance")

    def reset(self, save_file=None):
        if self._init:
            self._init = False
            # TODO: dump array in bg

    def get_fig(self):
        if self._fig is None:
            self._fig = plt.figure()
            self._mng = plt.get_current_fig_manager()
        return self._fig

    figure = property(get_fig, None, "current figure for mpl plotting")

    def _fig_reset(self):
        'activate re-instantiation of figure/mng instances'
        self._fig = None
        self.get_fig()

    def close(self, arg=None):
        '''
        Close our mpl figure
        '''
        if arg is not None:
            plt.close(arg)
        elif self._fig is not None:
            # FIXME: find a better way to do this
            # such that the window is not longer displayed
            # but also it is not 'destroyed' and removed from mem
            plt.close(self._fig)

    def clear(self):
        '''
        Clear the figure and all referenced axes
        '''
        if self.fig is not None:
            self.fig.clear()
            self.fig.canvas.draw()
        self._axes.clear()

    def plot(self, *args, **kwargs):
        '''
        Plot all columns in separate axes on our figure

        Parameters
        ----------
        args, kwargs : same as for mpl.axes.Axes.plot
        '''
        if not self._init:
            raise RuntimeError("You must initialize this metric set before "
                               "plotting it (ie. call 'setup' !")

        # if the window manager has been closed then
        # re-instantiate the figure
        if getattr(self._mng, 'window', None) is None:
            self._fig_reset()

        if hasattr(self, '_title'):
            self.title = self._title

        # render an axes index set
        axes = OrderedDict()
        for name, dtype in self.fields.items():
            try:
                iax = self._plot_opts[name]['axes']
                if iax is None:
                    # do not plot this field's array
                    continue
                axes[name] = iax[0]
            except KeyError:
                axes[name] = len(set(axes.values())) + 1

        num_axes = len(set(axes.values()))

        # plot loop
        for name, ax_index in axes.items():
            plot_opts = self._plot_opts[name].copy()
            plot_opts.pop('axes', None)

            # generate plots
            ax = self.fig.add_subplot(num_axes, 1, axes[name])
            ax.plot(getattr(self, name), label=name, **plot_opts)

            # set legend
            ax.legend(loc='upper right')

            # set titles
            # ax.set_title(name, fontdict=self.font_style)
            ax.set_xlabel('Call Event Index', fontdict=self.font_style)
            # store the axes and artist for later use
            # TODO: use a namedtuple here...
            self._axes[name] = ax

        # show in a window
        self.fig.show()


def load_from_dir(path='./*.pkl', mtype=Plotter):
    '''
    Autoload all pickeled arrays in a dir into Metric
    instances and plot

    Parameters
    ----------
    path : string, optional
        file system path + glob pattern to scan for files
    mtype : Metrics-like
        (sub-)class of type Metrics which will be used to load pickled data
    '''
    file_names = glob.glob(path)
    metrics = []
    for f in file_names:
        try:
            m = mtype(f)
            m.plot()
            metrics.append(m)
        except:
            pass
    return metrics


def close_all(opt='all'):
    plt.close(opt)


class LoadMetrics(Plotter):
    '''
    Metrics for load testing
    '''
    field_sig = OrderedDict([
        ('time', {
            'dtype': np.float32,
            'axes': None,  # indicates this field will not be plotted
        }),
        # latencies
        ('invite_latency', {
            'dtype': np.float32,
            'axes': (1, 1),
        }),
        ('answer_latency', {
            'dtype': np.float32,
            'axes': (1, 1),
        }),
        ('call_setup_latency', {
            'dtype': np.float32,
            'axes': (1, 1),
        }),
        ('originate_latency', {
            'dtype': np.float32,
            'axes': (1, 1)
        }),
        # counts
        ('num_failed_calls', {
            'dtype': np.uint16,
            'axes': (2, 1),
        }),
        # TODO: change name to num_seizures
        ('num_sessions', {
            'dtype': np.uint16,
            'axes': (2, 1),
        }),
    ])


def gen_hist(arr, col='invite_latency'):
    arr = arr[col]
    fig = plt.figure()  # always render new plots
    bins = np.arange(float(np.ceil(arr.max())))
    n, bins, patches = plt.hist(arr, bins=bins, normed=True)
    fig.show()
    return n, bins, patches
