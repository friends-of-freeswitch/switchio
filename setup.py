#!/usr/bin/env python2.7
from setuptools import setup


with open('README.rst') as f:
    readme = f.read()


setup(
    name="Switchy",
    version='0.1.alpha',
    description='Switchy is a fast FreeSWITCH ESL control library with '
                'an emphasis on load testing.',
    long_description=readme,
    license='Mozilla',
    author='Tyler Goodlet',
    author_email='tgoodlet@sangoma.com',
    url='',
    platforms=['linux'],
    packages=[
        'switchy',
        'switchy.apps',
        # 'tests',
    ],
    # use_2to3 = False
    # zip_safe=True,
    extras_require={
        'metrics': ['numpy'],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Mozilla License',
        'Operating System :: Linux',
        'Programming Language :: Python :: 2.7',
        'Topic :: Software Development',
        'Topic :: Software Development :: Testing',
        'Topic :: Software Development :: Quality Assurance',
        'Topic :: System :: Clustering',
        'Topic :: Utilities',
    ],
)
