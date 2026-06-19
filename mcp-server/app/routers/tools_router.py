import logging
from fastapi import APIRouter, HTTPException
from app.routers.contracts.tool_interface import TOOLS_SCHEMA, TOOL_DISPATCH, ToolCallRequest

router = APIRouter()
logger = logging.getLogger("tools_router")


@router.get("/tools")
async def list_tools():
    logger.info("REST list_tools")
    return TOOLS_SCHEMA


@router.post("/tool/call")
async def call_tool(request: ToolCallRequest):
    logger.info("REST call_tool name=%s arguments=%s", request.name, request.arguments)
    if request.name not in TOOL_DISPATCH:
        raise HTTPException(status_code=404, detail=f"Tool '{request.name}' not found")
    return await TOOL_DISPATCH[request.name](request.arguments)
