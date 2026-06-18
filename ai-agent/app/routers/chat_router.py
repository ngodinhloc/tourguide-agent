from fastapi import APIRouter, Depends
from app.routers.contracts.chat_interface import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.container import container

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(lambda: container.chat_service),
):
    return await service.handle(request)
