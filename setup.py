#!/usr/bin/env python3
from setuptools import setup
from os import path

version_py = path.join('corostc', 'version.py')

d = {}
with open(version_py, 'r') as fh:
    exec(fh.read(), d)
    version_pep = d['__version__']

setup(
    name='corostc',
    version=version_pep,
    description="Access Coros Training Center's web api",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/dlenski/corostc',
    author='Daniel Lenski',
    author_email='dlenski@gmail.com',
    license='GPL v3 or later',
    packages=['corostc'],
    install_requires=['requests'],
    extras_require={
        'fitparse': ['fitparse'],
    },
)
