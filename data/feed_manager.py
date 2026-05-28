"""
Feed Manager — 協調所有資料源並驅動 DualPoolOrchestrator tick 循環
發布信號到 Redis pub/sub,供 WebSocket 轉發給前端
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from AutoTrading.main import DualPoolOrchestrator
from AutoTrading.data.binance_feed import make_binance_feeds
from AutoTrading.data.ibkr_feed import make_ibkr_feeds
from AutoTrading.data.mock_feed import make_crypto_feeds, make_stock_feeds

logger = logging.getLogger(__name__)

TICK_INTERVAL = int(os.getenv("TICK_INTERVAL_SECONDS", "60"))  # 每分鐘 tick 一次


class FeedManager:
    """
    統一管理 Binance / IBKR / Mock feeds,
    定期呼叫 orchestrator.tick_both() 並將結果發布到 Redis
    """

    def __init__(self, orchestrator: DualPoolOrchestrator, redis: aioredis.Redis):
        self.orch = orchestrator
        self.redis = redis

        # 嘗試建立真實 feed,失敗自動 fallback mock
        use_mock = os.getenv("USE_MOCK_FEED", "true").lower() == "true"
        if use_mock:
            logger.info("📦 使用 MockFeed (設定 USE_MOCK_FEED=false 切換真實源)")
            self._crypto_feeds = make_crypto_feeds()
            self._stock_feeds = make_stock_feeds()
        else:
            logger.info("🌐 嘗試連接 Binance testnet + IBKR")
            self._crypto_feeds_raw = make_binance_feeds()
            self._stock_feeds_raw = make_ibkr_feeds()
            # 將 feed objects 統一為 callable dict
            self._crypto_feeds = self._crypto_feeds_raw
            self._stock_feeds = self._stock_feeds_raw

        self._use_mock = use_mock

    def _get_crypto_data(self) -> dict:
        result = {}
        for sym, feed in self._crypto_feeds.items():
            result[sym] = feed.next() if self._use_mock else feed.fetch()
        return result

    def _get_stock_data(self) -> dict:
        result = {}
        for sym, feed in self._stock_feeds.items():
            result[sym] = feed.next() if self._use_mock else feed.fetch()
        return result

    async def _publish_signals(self, pool: str):
        """把最新 chat messages 發布到 Redis"""
        pool_obj = self.orch.crypto if pool == "crypto" else self.orch.stock
        channel_redis = f"chat:{'crypto-floor' if pool == 'crypto' else 'equities-floor'}"
        signal_channel = f"signals:{pool}"

        # 最新的 5 條聊天訊息
        recent = pool_obj.chat_messages[-5:]
        for msg in recent:
            await self.redis.publish(channel_redis, json.dumps(msg, ensure_ascii=False))

        # 最新快照摘要發布到 signals channel
        snap = pool_obj.get_pool_snapshot()
        summary = {
            "pool": pool,
            "open_positions": snap["portfolio"][f"{pool}_pool"]["open_positions"],
            "realized_pnl": snap["portfolio"][f"{pool}_pool"]["realized_pnl"],
            "active_bots": sum(
                1 for b in snap["bots"]
                if b["status"] in ("active", "breeding")
            ),
        }
        await self.redis.publish(signal_channel, json.dumps(summary))

    async def run_forever(self):
        """主循環 — 每 TICK_INTERVAL 秒執行一次"""
        logger.info(f"⏱ FeedManager 啟動,tick 間隔 {TICK_INTERVAL}s")
        while True:
            try:
                crypto_data = self._get_crypto_data()
                stock_data = self._get_stock_data()

                crypto_ctx = {
                    "macro_data": {"dxy_change_5d": -0.005, "us10y_bps_change_5d": 3, "vix": 18},
                    "sentiment_score": 0.55,
                    "social_volume_zscore": 0.8,
                }

                await self.orch.tick_both(
                    crypto_data=crypto_data,
                    stock_data=stock_data,
                    crypto_extras=crypto_ctx,
                )

                await self._publish_signals("crypto")
                await self._publish_signals("stock")

            except Exception as e:
                logger.error(f"[FeedManager] tick 錯誤: {e}", exc_info=True)

            await asyncio.sleep(TICK_INTERVAL)
