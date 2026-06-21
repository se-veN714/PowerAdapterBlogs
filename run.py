# -*- coding: utf-8 -*-
# @File    : run.py
# @Time    : 2025/8/21 03:37
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : qingyudong942@gmail.com

"""
本模块提供了项目运行测试功能的类和函数。
"""

# here put the import lib
from waitress import serve
from PowerAdapterBlogs.wsgi import application

serve(
    app=application,
    host='127.0.0.1',
    port=8000
)
