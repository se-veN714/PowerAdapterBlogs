# -*- coding: utf-8 -*-
# @File    : product.py
# @Time    : 2025/2/3 20:09
# @Author  : seveN1foR
# @Version : 1.0
# @Software: PyCharm
# @Contact : sevencdxxiv@qq.com

"""
本模块提供了上线时正式的设置
"""

# here put the import lib
import base64

from dotenv import load_dotenv

from .base import *

DEBUG = False

load_dotenv(BASE_DIR / '.env')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS').split(',')

DATABASES = {
    "default": {
        'ENGINE': "django.db.backends.postgresql",
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
    }
}

key_base64 = os.getenv('LOGINTEGRYIT_HMAC_KEY_BASE64')
LOG_HMAC_KEY = base64.b64decode(key_base64)
