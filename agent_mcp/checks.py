from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured
from .config import origin


@register(Tags.security)
def check_mcp_origin(app_configs, **kwargs):
    try:
        origin()
    except (ImproperlyConfigured, ValueError) as error:
        return [Error(str(error), id='agent_mcp.E001')]
    return []
