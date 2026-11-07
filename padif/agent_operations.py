"""Stable article operation vocabulary, distinct from client OAuth grants."""
from django.core.exceptions import ValidationError

READ = 'padif:read'
ANNOTATE = 'padif:annotate'
VERSION = 'padif:version'
OPERATIONS = (READ, ANNOTATE, VERSION)
LABELS = {READ: '阅读', ANNOTATE: '批注', VERSION: '分支写作'}

def role_operations(role):
    return list(OPERATIONS) if role in {'owner', 'collaborator'} else [READ] if role == 'viewer' else []

def normalize_operations(values, role=None):
    if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) or v not in OPERATIONS for v in values):
        raise ValidationError('未知的 AI+ 操作权限。')
    result = [key for key in OPERATIONS if key in values]
    if result and READ not in result:
        raise ValidationError('非空 AI+ 权限必须包含阅读；关闭阅读将放弃整篇授权。')
    if role is not None and not set(result).issubset(role_operations(role)):
        raise ValidationError('目标操作超出本文人类角色权限。')
    return result

def operation_summary(values):
    return ' / '.join(LABELS[key] for key in OPERATIONS if key in values) or '无'
