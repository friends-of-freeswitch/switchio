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
import sys
from os.path import basename
import matplotlib.pyplot as plt
import numpy as np
import pylab
from ... import utils

log = utils.get_logger(__name__)

def multiplot(metrics, fieldspec=None, fig=None, mng=None, block=False):
    '''Plot all columns in appropriate axes on a figure
    (talk about reimplementing `pandas` like an dufus...)
    '''
    fig = fig if fig else plt.figure()
    mng = mng if mng else plt.get_current_fig_manager()
    if not fieldspec:
        # place each array on a separate axes
        fieldspec = [
            (name, (i, 1)) for i, name in enumerate(metrics.dtype.fields)
        ]
    elif hasattr(fieldspec, 'items'):
        fieldspec = fieldspec.items()

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
            try:
                array = metrics[name]
            except ValueError:
                log.warn("no row '{}' exists for '{}".format(name, metrics))
                print("no row '{}' exists for '{}".format(name, metrics))
                continue
        log.info("plotting '{}'".format(name))
        artists.append(
            ax.plot(
                array,
                label=name,
                # linewidth=2.0,
            )[0]
        )
        # set legend
        ax.legend(loc='upper left', fontsize='large')
        # set titles
        # ax.set_title(name, fontdict={'size': 'small'})
        ax.set_xlabel('Call Event Index', fontdict={'size': 'large'})

    # show in a window full size
    fig.tight_layout()
    if getattr(metrics, 'title', None):
        fig.suptitle(basename(metrics.title), fontsize=15)
    if block or sys.platform.lower() == 'darwin':
        # For MacOS only blocking mode is supported
        # the fig.show() method throws exceptions
        pylab.show()
    else:
        fig.show()
    return mng, fig, artists


def gen_hist(arr, col='invite_latency'):
    arr = arr[col]
    fig = plt.figure()  # always render new plots
    bins = np.arange(float(np.ceil(arr.max())))
    n, bins, patches = plt.hist(arr, bins=bins, normed=True)
    fig.show()
    return n, bins, patches
