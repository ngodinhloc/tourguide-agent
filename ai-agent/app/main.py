import logging
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import health, tour, chat

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("http")

app = FastAPI(title="Tour Guide Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    ms = int((time.time() - start) * 1000)
    logger.info("%s %s %s %dms", request.method, request.url.path, response.status_code, ms)
    return response


app.include_router(health.router, prefix="/api")
app.include_router(tour.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
