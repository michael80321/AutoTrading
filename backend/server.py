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
from autotrading.backend.db.session import init_db


async def startup():
    await init_db()
    logging.getLogger(__name__).info("✅ 資料庫初始化完成")


if __name__ == "__main__":
    asyncio.run(startup())
    uvicorn.run(
        "autotrading.backend.app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "production") == "development",
        log_level="info",
    )
