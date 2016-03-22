# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Measurement and plotting tools - pandas + mpl helpers
"""
# TODO:
# - make legend malleable
import sys
import os
from ... import utils
from collections import namedtuple

# handle remote execution plotting
if not os.environ.get("DISPLAY"):
    import matplotlib
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pylab

log = utils.get_logger(__name__)

plotitems = namedtuple('plotitems', 'mng fig axes artists')


def multiplot(df, figspec, fig=None, mng=None, block=False, fname=None):
    '''Plot selected columns in appropriate axes on a figure using the pandas
    plotting helpers where possible. `figspec` is a map of subplot location
    tuples to column name iterables.
    '''
    # figspec is a map of tuples like: {(row, column): [<column names>]}
    rows, cols = max(figspec)

    # generate fig and axes set
    fig, axes_arr = plt.subplots(
        rows,
        cols,
        sharex=True,
        squeeze=False,
        tight_layout=True,
        # make a BIG plot if we're writing to file
        figsize=(2*24, 1*24) if fname else None,
    )
    mng = mng if mng else plt.get_current_fig_manager()

    if block or fname:
        # turn interactive mode off
        plt.ioff()

    # plot loop
    artist_map = {}
    axes = {}
    for loc, colnames in sorted(figspec.items()):
        if loc is None:
            continue
        else:
            row, col = loc[0] - 1, loc[1] - 1

        ax = axes_arr[row, col]
        log.info("plotting '{}'".format(colnames))
        ax = df[colnames].plot(ax=ax)  # use the pandas plotter
        axes[loc] = ax
        artists, names = ax.get_legend_handles_labels()
        artist_map[loc] = {
            name: artist for name, artist in zip(names, artists)}

        # set legend
        ax.legend(
            artists, names,
            loc='upper left', fontsize='large', fancybox=True, framealpha=0.5
        )

    ax.set_xlabel('Call Event Index', fontdict={'size': 'large'})

    if getattr(df, 'title', None):
        fig.suptitle(os.path.basename(df.title), fontsize=15)

    if block:
        if sys.platform.lower() == 'darwin':
            # For MacOS only blocking mode is supported
            # the fig.show() method throws exceptions
            pylab.show()
        else:
            plt.show()
    # save to file depending on fname extension
    elif fname:
        plt.savefig(fname, bbox_inches='tight')
    # regular interactive plotting
    else:
        fig.show()

    return plotitems(mng, fig, axes, artist_map)
