"""
後端啟動腳本
python backend/server.py
或
uvicorn backend.app:app --reload --port 8000
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 載入 .env
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
from backend.db.session import init_db


async def startup():
    await init_db()
    logging.getLogger(__name__).info("✅ 資料庫初始化完成")


if __name__ == "__main__":
    asyncio.run(startup())
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "production") == "development",
        log_level="info",
    )
