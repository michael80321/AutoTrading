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


async def _try_init_db():
    """資料庫初始化 — 非致命。連不上 Postgres 也絕不能擋住 uvicorn 啟動。"""
    try:
        from autotrading.backend.db.session import init_db
        await asyncio.wait_for(init_db(), timeout=10.0)
        logger.info("✅ 資料庫初始化完成")
    except Exception as e:
        logger.warning(f"資料庫初始化略過（不影響服務）: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(_try_init_db())
    except Exception as e:
        logger.warning(f"startup 階段略過: {e}")
    uvicorn.run(
        "autotrading.backend.app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "production") == "development",
        log_level="info",
    )
