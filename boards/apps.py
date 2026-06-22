"""Boards 应用配置。

管理首页 Editorial 板块（Skateboard / Music / Coding 等），
每个板块可独立配置名称、颜色、关键词和关联分类。
"""

from django.apps import AppConfig


class BoardsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'boards'
    verbose_name = '首页板块'
