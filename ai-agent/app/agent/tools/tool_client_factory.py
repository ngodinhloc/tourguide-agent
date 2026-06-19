from app.agent.tools.tool_client_interface import ToolClientInterface
from app.agent.tools.mcp_tools import McpTools
from app.agent.tools.rest_tools import RestTools


class ToolClientFactory:
    def __init__(self, mcp_server_url: str, mcp_protocol: str):
        self._mcp_server_url = mcp_server_url
        self._mcp_protocol = mcp_protocol

    def create(self) -> ToolClientInterface:
        if self._mcp_protocol == "MCP":
            return McpTools(self._mcp_server_url)
        return RestTools(self._mcp_server_url)
