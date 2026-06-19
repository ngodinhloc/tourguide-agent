import httpx
from app.agent.tools.tool_client_interface import ToolClientInterface


class RestTools(ToolClientInterface):
    def __init__(self, mcp_server_url: str):
        self._url = f"{mcp_server_url}/api/tool/call"

    async def call(self, name: str, arguments: dict):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._url,
                json={"name": name, "arguments": arguments},
            )
            resp.raise_for_status()
            return resp.json()
