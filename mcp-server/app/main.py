import logging
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.configs.settings import settings
from app.fast_mcp import fast_mcp
from app.routers import health_router, tools_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("http")

_mcp_app = fast_mcp.http_app(path="/")
app = FastAPI(title="Tour Guide MCP Server", lifespan=_mcp_app.lifespan)

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
    if request.url.path.startswith("/mcp") and request.method == "POST":
        body = await request.body()
        logger.info("MCP %s %s", request.method, body.decode())
    else:
        logger.info("REST %s %s", request.method, request.url.path)
    response = await call_next(request)
    ms = int((time.time() - start) * 1000)
    logger.info("%s %s %s %dms", request.method, request.url.path, response.status_code, ms)
    return response


app.include_router(health_router.router, prefix="/api")
app.include_router(tools_router.router, prefix="/api")
app.mount("/mcp", _mcp_app)
