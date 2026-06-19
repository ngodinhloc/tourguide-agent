import json
import logging
from fastmcp import Client
from mcp.types import TextContent
from app.agent.tools.tool_client_interface import ToolClientInterface

logger = logging.getLogger("mcp_tools")


class McpTools(ToolClientInterface):
    def __init__(self, mcp_server_url: str):
        self._url = f"{mcp_server_url}/mcp/"

    async def call(self, name: str, arguments: dict):
        async with Client(self._url) as client:
            result = await client.call_tool(name, arguments)
            if result.content and isinstance(result.content[0], TextContent):
                return json.loads(result.content[0].text)
            return {}
