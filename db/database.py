"""Async SQLAlchemy engine for PostgreSQL/TimescaleDB"""
from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "")

engine = None
AsyncSessionLocal = None

def init_db(url: str):
    global engine, AsyncSessionLocal
    engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
