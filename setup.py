#!/usr/bin/env python2.7
from setuptools import setup


with open('README.rst') as f:
    readme = f.read()


setup(
    name="switchy",
    version='0.1.alpha',
    description='Switchy is a fast FreeSWITCH ESL control library with '
                'an emphasis on load testing.',
    long_description=readme,
    license='Mozilla',
    author='Sangoma Technologies',
    author_email='qa@eng.sangoma.com',
    url='https://github.com/sangoma/switchy',
    platforms=['linux'],
    packages=[
        'switchy',
        'switchy.apps',
        'switchy.apps.measure',
        # 'tests',
    ],
    entry_points={
        'console_scripts': [
            'switchy = switchy.cli:cli',
        ]
    },
    install_requires=['click'],
    package_data={
        'switchy': ['../conf/switchydp.xml']
    },
    # use_2to3 = False
    # zip_safe=True,
    extras_require={
        'metrics': ['numpy'],
        'graphing': ['matplotlib'],
        'testing': ['pytest'],
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
