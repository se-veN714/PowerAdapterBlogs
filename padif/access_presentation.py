"""Present module eligibility and article consent as separate states."""
from agent_mcp.access import can_use_agent
from .agent_operations import READ, operation_summary, role_operations


def article_access_state(user, role, grant, pending=None):
    qualified = can_use_agent(user)
    operations = grant.allowed_operations if grant and grant.is_enabled else []
    effective = qualified and READ in operations and READ in role_operations(role)
    if effective:
        state, label = 'enabled', '本文 AI+ 已生效'
        if pending:
            label += ' · 提权待审核'
    elif pending:
        state, label = 'pending', '本文 AI+ 待审核'
    elif operations:
        state, label = 'unavailable', '本文 AI+ 暂不可用'
    elif grant and grant.revoked_at:
        state, label = 'revoked', '本文 AI+ 已撤销'
    else:
        state, label = 'none', '本文 AI+ 未授权'
    return {'module_enabled': qualified, 'module_label': 'PAdif Agent 已开通' if qualified else 'PAdif Agent 未开通',
            'state': state, 'label': label, 'effective': bool(effective),
            'operations_summary': operation_summary(operations), 'pending': pending}
