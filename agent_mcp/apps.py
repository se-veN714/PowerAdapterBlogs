from django.apps import AppConfig


class AgentMcpConfig(AppConfig):
    name = 'agent_mcp'
    verbose_name = 'PAdif MCP 授权'

    def ready(self):
        from . import checks  # noqa: F401
        from . import signals  # noqa: F401
