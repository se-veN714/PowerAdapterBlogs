# -*- coding: utf-8 -*-
# @File    : cus_site.py
# @Time    : 2025/2/20 01:49
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了XXX功能的类和函数。
"""
from django.contrib.admin import AdminSite


# here put the import lib
class CustomSite(AdminSite):
    site_header = 'PowerAdapterBlogs'
    site_title = 'PowerAdapterBlogs 管理后台'
    index_title = '首页'


custom_site = CustomSite(name='cus_admin')