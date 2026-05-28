"""
資料庫 session — SQLAlchemy async + TimescaleDB/PostgreSQL
環境變數: DATABASE_URL (預設 SQLite for 開發)
"""
import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

def _fix_db_url(url: str) -> str:
    # Railway / Supabase 給的是 postgres:// 或 postgresql://，asyncpg 需要 postgresql+asyncpg://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = _fix_db_url(
    os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./autotrading.db")
)

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
