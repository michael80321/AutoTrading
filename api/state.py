"""
全域共享狀態 — 由 api/main.py 在 startup 時初始化
其他模組透過 import 取得 orchestrator / redis_client
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from AutoTrading.main import DualPoolOrchestrator

orchestrator: "DualPoolOrchestrator | None" = None
redis_client: "aioredis.Redis | None" = None
