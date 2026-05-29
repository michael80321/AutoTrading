"""
後端啟動腳本
python -m autotrading.backend.server
或
uvicorn autotrading.backend.app:app --port 8000
"""
import asyncio
import logging
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

import uvicorn

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"🚀 啟動單機服務於 0.0.0.0:{port}")
    uvicorn.run(
        "autotrading.backend.app:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENV", "production") == "development",
        log_level="info",
    )
