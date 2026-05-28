"""
Redis pub/sub 匯流排 — 雙池警示廣播 + 即時信號分發
頻道:
  trading:crypto:signals  — 加密池信號/聊天
  trading:stock:signals   — 美股池信號/聊天
  trading:cross:warnings  — 跨池警示
  trading:system:events   — 系統事件(熔斷/進化)
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis 套件未安裝,使用記憶體模式")


CHANNELS = {
    "crypto": "trading:crypto:signals",
    "stock": "trading:stock:signals",
    "cross": "trading:cross:warnings",
    "system": "trading:system:events",
}


class RedisBus:
    def __init__(self, url: str = "redis://localhost:6379"):
        self.url = url
        self._client: Optional[object] = None
        self._pubsub: Optional[object] = None
        self._connected = False

    async def connect(self):
        if not REDIS_AVAILABLE:
            logger.warning("Redis 不可用,跨池廣播停用")
            return
        try:
            self._client = aioredis.from_url(self.url, decode_responses=True)
            await self._client.ping()
            self._connected = True
            logger.info(f"✅ Redis 已連線: {self.url}")
        except Exception as e:
            logger.warning(f"Redis 連線失敗 ({e}),使用降級模式")
            self._connected = False

    async def disconnect(self):
        if self._client and self._connected:
            await self._client.aclose()

    async def ping(self) -> bool:
        if not self._connected or not self._client:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def publish(self, channel_key: str, payload: dict):
        channel = CHANNELS.get(channel_key, channel_key)
        if not self._connected or not self._client:
            return
        try:
            await self._client.publish(channel, json.dumps(payload, default=str))
        except Exception as e:
            logger.error(f"Redis publish 失敗: {e}")

    async def subscribe_and_forward(self, ws_manager):
        """訂閱所有頻道並轉發給對應 WebSocket 連線，斷線自動重連"""
        if not self._connected or not self._client:
            return
        backoff = 1
        while self._connected:
            try:
                pubsub = self._client.pubsub()
                await pubsub.subscribe(*CHANNELS.values())
                backoff = 1
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    data = json.loads(message["data"])
                    channel = message["channel"]
                    pool = "crypto" if "crypto" in channel else "stock"
                    await ws_manager.broadcast(pool, data)
            except Exception as e:
                logger.warning(f"Redis subscribe 斷線 ({e})，{backoff}s 後重連")
                import asyncio
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
