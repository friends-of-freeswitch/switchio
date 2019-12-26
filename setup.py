#!/usr/bin/env python
#
# Copyright 2014 Sangoma Technologies Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from setuptools import setup

with open('README.rst', encoding='utf-8') as f:
    readme = f.read()


setup(
    name="switchio",
    version='0.1.0.a6~mgwilliams',
    description='asyncio powered FreeSWITCH cluster control',
    long_description=readme,
    license='Mozilla',
    author='Sangoma Technologies',
    maintainer='Tyler Goodlet',
    maintainer_email='tgoodlet@gmail.com',
    url='https://github.com/friends-of-freeswitch/switchio',
    platforms=['linux'],
    packages=[
        'switchio',
        'switchio.apps',
        'switchio.apps.measure',
    ],
    entry_points={
        'console_scripts': [
            'switchio = switchio.cli:cli',
        ]
    },
    install_requires=['click', 'colorlog'],
    package_data={
        'switchio': ['../conf/switchiodp.xml']
    },
    extras_require={
        'metrics': ['pandas>=0.18'],
        'hdf5': ['tables==3.2.1.1'],
        'graphing': ['matplotlib', 'pandas>=0.18'],
    },
    tests_require=['pytest'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Intended Audience :: Telecommunications Industry',
        'Intended Audience :: Developers',
        'Topic :: Communications :: Telephony',
        'Topic :: Software Development :: Testing :: Traffic Generation',
        'Topic :: System :: Clustering',
        'Environment :: Console',
    ],
)
