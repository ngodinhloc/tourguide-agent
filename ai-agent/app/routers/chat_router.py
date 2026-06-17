from fastapi import APIRouter, Depends
from app.routers.contracts.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.di import get_chat_service

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
):
    return await service.handle(request)
