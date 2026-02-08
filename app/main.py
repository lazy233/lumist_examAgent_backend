import logging
import os
import time
from pathlib import Path

# 在导入 config 前加载项目根目录 .env，与迁移脚本使用同一 DATABASE_URL
_root = Path(__file__).resolve().parent.parent
_env = _root / ".env"
if _env.is_file():
    with open(_env, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k and os.environ.get(k) is None:
                    os.environ[k] = v

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.api.router import api_router
from app.core.config import settings
from app.core.storage import ensure_storage_dirs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        addr = request.client.host if request.client else "-"
        logger.info(f'{addr} - "{request.method} {request.url.path}" {response.status_code} ({elapsed:.0f}ms)')
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="Lumist ExamAgent Backend")
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
ensure_storage_dirs()
