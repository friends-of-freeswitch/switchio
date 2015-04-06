# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Measurement and plotting tools - numpy + mpl helpers
"""
# TODO:
#     - figure.tight_layout doesn't seem to work??
#     - make legend malleable
#     - consider a way to easily move lines to different axes and
from collections import OrderedDict
import matplotlib.pyplot as plt
import numpy as np


def plot(metrics, fieldspec=None, fig=None, mng=None):
    '''Plot all columns in appropriate axes on a figure
    '''
    fig = fig if fig else plt.figure()
    mng = mng if mng else plt.get_current_fig_manager()
    if not fieldspec:
        # place each array on a separate axes
        fieldspec = [
            (name, (i, 1)) for i, name in enumerate(metrics.dtype.fields)
        ]
    rows, cols = max(tup[1] for tup in fieldspec)

    # plot loop
    artists = []  # store the artists for later use
    for name, loc in fieldspec:
        if loc is None:
            continue
        else:
            row, col = loc
        # generate plots
        ax = fig.add_subplot(rows, cols, row * col)
        try:
            array = getattr(metrics, name)
        except AttributeError:
            array = metrics[name]
        print("plotting '{}'".format(name))
        artists.append(ax.plot(array, label=name)[0])  # , **plot_opts)
        # set legend
        ax.legend(loc='upper right')
        # set titles
        # ax.set_title(name, fontdict={'size': 'small'})
        ax.set_xlabel('Call Event Index', fontdict={'size': 'small'})

    # show in a window full size
    fig.tight_layout()
    fig.show()
    return mng, fig, artists


def gen_hist(arr, col='invite_latency'):
    arr = arr[col]
    fig = plt.figure()  # always render new plots
    bins = np.arange(float(np.ceil(arr.max())))
    n, bins, patches = plt.hist(arr, bins=bins, normed=True)
    fig.show()
    return n, bins, patches
