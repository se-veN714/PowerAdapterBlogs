# -*- coding: utf-8 -*-
# @File    : setup.py
# @Time    : 2025/8/21 02:33
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了setup功能的类和函数。
"""

# here put the import lib
from setuptools import setup, find_packages

setup(
    name='PowerAdapterBlogs',
    version='0.0.1',
    description='PowerAdapterBlogs-Blog System base on Django',
    author='PowerAdapter',
    author_email='qingyudong942@gmail.com',
    license='MIT',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "Django>=4.2",
        "psycopg2-binary>=2.9",
        "django-redis>=6.0",
        "redis>=6.4",
        "django-widget-tweaks>=1.5",
        "django-mathfilters>=1.0",
        "django-jazzmin>=3.0.0",
        "django-autocomplete-light>=3.11",
        "drf-spectacular>=0.28",
        "drf-spectacular-sidecar>=2025.8",
        "Markdown>=3.8",
        "gmssl>=3.2.2",
    ],
    extras_require={
        "dev": [
            "django-debug-toolbar>=4.0",
            "django-extensions>=3.0",
            "ruff>=0.1",
        ],
        "test": [
            "pytest>=7.0",
            "pytest-django>=4.5",
            "coverage>=7.0",
            "faker>=17.0",  # 用于测试数据
        ],
    },
    scripts=[
        'manage.py',
    ],
    entry_points={
        'console_scripts': [
            'PowerAdapter_manage = manage:main',
        ]
    },
    classifiers=[
        # 版本
        "Development Status :: 3 - Alpha",
        # 受众
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        # 许可证
        "License :: OSI Approved :: MIT License",
        # Python 版本
        "Programming Language :: Python :: 3.6",
        "Framework :: Django",
    ]
)
