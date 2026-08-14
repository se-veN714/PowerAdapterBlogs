from django import template

register = template.Library()


def _value(value, suffix=""):
    return "不可用" if value is None else f"{value}{suffix}"


@register.filter
def content_pulse_body(data):
    return (
        f"草稿  {_value(data['draft_count'])}\n"
        f"待审核  {_value(data['review_count'])}\n"
        f"排期  {_value(data['scheduled_count'])}\n\n"
        f"本月完成度  {_value(data['monthly_completion'], '%')}"
    )


@register.filter
def moderation_body(data):
    return (
        f"高风险  {_value(data['high_risk_count'])}\n"
        f"最久等待  {_value(data['longest_wait_label'])}\n\n"
        "评论队列需要逐条判断"
    )


@register.filter
def audience_body(data):
    points = data.get("hourly_points") or []
    bars = " ".join(str(point) for point in points) if points else "暂无小时数据"
    return f"独立访客  {data['unique_visitors']}\n\n3H BUCKETS\n{bars}"


@register.filter
def asset_body(data):
    return (
        f"存储占用  {_value(data['storage_label'])}\n"
        f"未引用  {_value(data['unused_count'])}\n"
        f"待优化  {_value(data['optimization_count'])}"
    )


@register.filter
def security_body(data):
    return (
        f"二次验证  {data['mfa_label']}\n"
        f"今日审计事件  {_value(data['audit_event_count'])}\n"
        f"拒绝动作  {_value(data['rejected_action_count'])}\n\n"
        f"外部 uptime  {_value(data['external_uptime_label'])}"
    )
