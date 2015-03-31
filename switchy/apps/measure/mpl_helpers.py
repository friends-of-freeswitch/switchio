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
#     - consider a way to easily move lines to different axes and
#       re-rendering leveraging ipython tab completion
from collections import OrderedDict
import matplotlib.pyplot as plt
import numpy as np


def plot(metrics, field_opts={}):
    '''Plot all columns in appropriate axes on a figure
    '''
    fig = plt.figure()
    mng = plt.get_current_fig_manager()

    # render an axes index set
    axes = OrderedDict()
    for name, dtype in metrics.dtype.fields.items():
        if name in field_opts:
            iax = field_opts[name]
            if iax is None:
                # do not plot this field's array
                continue
            axes[name] = iax[0]
        else:
            axes[name] = len(set(axes.values())) + 1

    num_axes = len(set(axes.values()))

    # plot loop
    artists = []
    for name, ax_index in axes.items():
        # generate plots
        ax = fig.add_subplot(num_axes, 1, axes[name])
        array = getattr(metrics, name, metrics[name])
        artists.append(ax.plot(array, label=name)[0])  # , **plot_opts)

        # set legend
        ax.legend(loc='upper right')
        # set titles
        # ax.set_title(name, fontdict={'size': 'small'})
        ax.set_xlabel('Call Event Index', fontdict={'size': 'small'})
        # store the axes and artist for later use

    # show in a window full size
    fig.tight_layout()
    fig.show()
    return mng, fig, artists


def close_all(opt='all'):
    plt.close(opt)


def gen_hist(arr, col='invite_latency'):
    arr = arr[col]
    fig = plt.figure()  # always render new plots
    bins = np.arange(float(np.ceil(arr.max())))
    n, bins, patches = plt.hist(arr, bins=bins, normed=True)
    fig.show()
    return n, bins, patches
