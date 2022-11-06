#!/usr/bin/env python

from setuptools import setup, find_packages
setup(
    name="swing-python-handler",
    version='1.0.0',
    description="Logging handler to send logs to your swing account with bulk rpc",
    keywords="logging handler swing bulk https",
    author="logzio",
    maintainer="salem ododa",
    mail="salem@brainstorm.ng",
    url="https://github.com/salemzii/swing-python-handler",
    license="Apache License 2", 
    packages=find_packages(),
    install_requires=[
        "requests>=2.27.0",
        "protobuf==3.20.1",
        "opentelemetry-instrumentation-logging==0.32b0"
    ],

    test_requires=[
        "future"
    ],

    include_package_data=True,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.9'
    ]
)
