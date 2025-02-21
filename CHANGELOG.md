# CHANGE LOG

## [Unreleased]

日期：2025年2月22日

- 修复 TemplatesDoNotExist Error

> 原因：
> BASE_DIR 为 Django 项目地址，而非根目录

```python 
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
```

- 修改 db.sqlite3 位置

> 由 Django 项目地址更改为根目录

- 完成视图的初步设计，以及视图的部分html