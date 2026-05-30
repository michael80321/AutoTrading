"""
執行層 — 加密走 Binance、美股走 IBKR
分開資金池:加密 $2,700 / 美股 $2,700,各自獨立風控
所有訂單自動掛 OCO (止損 + 止盈),分批 TP
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
import logging

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class ExecutionOrder:
    order_id: str
    pool: Literal["crypto", "stock"]
    symbol: str
    side: Literal["LONG", "SHORT"]
    qty: float
    entry_price: float
    stop_loss: float
    take_profit: list[float]
    tp_split: list[float] = field(default_factory=lambda: [0.5, 0.5])  # 分批比例
    status: OrderStatus = OrderStatus.PENDING
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    contributors: list[str] = field(default_factory=list)
    consensus_score: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0


class ExecutionRouter:
    """
    雙路由執行層:加密 Binance + 美股 IBKR
    """
    
    def __init__(
        self,
        crypto_pool_usdt: float = 2700.0,
        stock_pool_usd: float = 2700.0,
        fee_rate_crypto: float = 0.0004,
        fee_rate_stock: float = 0.0005,
        max_concurrent_positions: int = 8,
        binance_client=None,    # ccxt.binance() 實例
        ibkr_client=None,       # ib_insync.IB() 實例
    ):
        self.crypto_pool = crypto_pool_usdt
        self.stock_pool = stock_pool_usd
        self.fee_rate_crypto = fee_rate_crypto
        self.fee_rate_stock = fee_rate_stock
        self.max_concurrent = max_concurrent_positions
        self.binance = binance_client
        self.ibkr = ibkr_client
        
        self.open_orders: dict[str, ExecutionOrder] = {}
        self.closed_orders: list[ExecutionOrder] = []
    
    def _classify_pool(self, symbol: str) -> Literal["crypto", "stock"]:
        crypto_suffixes = ("USDT", "USDC", "BUSD", "BTC", "ETH", "USD-PERP")
        return "crypto" if symbol.endswith(crypto_suffixes) or "-PERP" in symbol else "stock"
    
    def _available_capital(self, pool: str) -> float:
        in_use = sum(o.qty * o.entry_price for o in self.open_orders.values() if o.pool == pool)
        total = self.crypto_pool if pool == "crypto" else self.stock_pool
        return total - in_use
    
    async def submit(self, consensus_result, symbol: str) -> Optional[ExecutionOrder]:
        """
        從共識引擎接收 ConsensusResult,提交訂單
        """
        pool = self._classify_pool(symbol)
        available = self._available_capital(pool)
        
        if len([o for o in self.open_orders.values() if o.pool == pool]) >= self.max_concurrent:
            logger.warning(f"{pool} 池已達最大並發部位 {self.max_concurrent}")
            return None
        
        # 倉位大小 = 池子總額 × 風險% / 止損距離%
        total_pool = self.crypto_pool if pool == "crypto" else self.stock_pool
        risk_amount = total_pool * consensus_result.risk_pct
        sl_dist = abs(consensus_result.entry - consensus_result.stop_loss)
        qty = risk_amount / sl_dist if sl_dist > 0 else 0
        
        # 不能超過可用資金
        max_qty_by_capital = available / consensus_result.entry
        qty = min(qty, max_qty_by_capital * 0.95)  # 留 5% buffer
        
        if qty * consensus_result.entry < 10:  # 最低名目價值
            logger.info(f"{symbol} 名目價值過低,跳過")
            return None
        
        order = ExecutionOrder(
            order_id=f"{pool}-{symbol}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            pool=pool,
            symbol=symbol,
            side=consensus_result.side,
            qty=round(qty, 6),
            entry_price=consensus_result.entry,
            stop_loss=consensus_result.stop_loss,
            take_profit=consensus_result.take_profit,
            contributors=consensus_result.contributors,
            consensus_score=consensus_result.total_weight,
        )
        
        # 實際下單
        if pool == "crypto":
            success = await self._submit_binance(order)
        else:
            success = await self._submit_ibkr(order)
        
        if success:
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.now()
            self.open_orders[order.order_id] = order
            return order
        return None
    
    async def _submit_binance(self, order: ExecutionOrder) -> bool:
        """提交至 Binance 合約 — 市價進場 + STOP_MARKET 止損 + TAKE_PROFIT_MARKET 止盈"""
        if self.binance is None:
            logger.info(f"[DRY-RUN] 合約 {order.symbol} {order.side} qty={order.qty:.4f}")
            return True
        try:
            side = "buy" if order.side == "LONG" else "sell"
            opp_side = "sell" if side == "buy" else "buy"
            # 精度處理：合約數量需符合 lot size
            markets = await self.binance.load_markets()
            market = markets.get(order.symbol) or markets.get(order.symbol.replace("USDT", "/USDT"))
            qty = order.qty
            if market:
                precision = market.get("precision", {}).get("amount", 3)
                qty = round(order.qty, precision)
            # 取整後若數量歸零，放棄下單避免送出無效訂單
            if qty <= 0:
                logger.warning(f"{order.symbol} 取整後數量為 0，跳過下單")
                order.status = OrderStatus.REJECTED
                return False
            # 把實際下單數量寫回 order，確保後續平倉數量一致
            order.qty = qty

            # 1. 市價開倉
            await self.binance.create_market_order(order.symbol, side, qty)

            # 2. 止損單 STOP_MARKET（全倉 reduceOnly）
            await self.binance.create_order(
                order.symbol, "STOP_MARKET", opp_side, qty, None,
                {"stopPrice": order.stop_loss, "reduceOnly": True},
            )

            # 3. 止盈單 TAKE_PROFIT_MARKET（TP1 = 全數平倉）
            if order.take_profit:
                await self.binance.create_order(
                    order.symbol, "TAKE_PROFIT_MARKET", opp_side, qty, None,
                    {"stopPrice": order.take_profit[0], "reduceOnly": True},
                )

            order.fees_paid = qty * order.entry_price * self.fee_rate_crypto
            logger.info(f"✅ 合約下單 {order.symbol} {order.side} qty={qty} SL={order.stop_loss} TP={order.take_profit[0] if order.take_profit else 'N/A'}")
            return True
        except Exception as e:
            logger.error(f"Binance 合約下單失敗: {e}")
            order.status = OrderStatus.REJECTED
            return False
    
    async def _submit_ibkr(self, order: ExecutionOrder) -> bool:
        """提交至 IBKR — Bracket Order (進場 + 止損 + 止盈)"""
        if self.ibkr is None:
            logger.info(f"[DRY-RUN] IBKR {order.symbol} {order.side} qty={order.qty}")
            return True
        try:
            from ib_insync import Stock, MarketOrder, StopOrder, LimitOrder
            contract = Stock(order.symbol, "SMART", "USD")
            action = "BUY" if order.side == "LONG" else "SELL"
            opp_action = "SELL" if action == "BUY" else "BUY"
            
            parent = MarketOrder(action, order.qty, transmit=False)
            sl_order = StopOrder(opp_action, order.qty, order.stop_loss,
                                 parentId=parent.orderId, transmit=False)
            tp_orders = []
            for i, tp in enumerate(order.take_profit):
                split_qty = order.qty * order.tp_split[i] if i < len(order.tp_split) else order.qty / len(order.take_profit)
                tp_o = LimitOrder(opp_action, split_qty, tp,
                                  parentId=parent.orderId,
                                  transmit=(i == len(order.take_profit) - 1))
                tp_orders.append(tp_o)
            
            self.ibkr.placeOrder(contract, parent)
            self.ibkr.placeOrder(contract, sl_order)
            for tp_o in tp_orders:
                self.ibkr.placeOrder(contract, tp_o)
            order.fees_paid = order.qty * order.entry_price * self.fee_rate_stock
            return True
        except Exception as e:
            logger.error(f"IBKR 下單失敗:{e}")
            order.status = OrderStatus.REJECTED
            return False
    
    def on_fill(self, order_id: str, fill_price: float, fill_qty: float):
        """成交回調"""
        order = self.open_orders.get(order_id)
        if not order:
            return
        order.status = OrderStatus.FILLED if fill_qty >= order.qty else OrderStatus.PARTIALLY_FILLED
        order.filled_at = datetime.now()
    
    def on_close(self, order_id: str, close_price: float, reason: str):
        """部位關閉回調 — 計算 P&L"""
        order = self.open_orders.pop(order_id, None)
        if not order:
            return
        direction = 1 if order.side == "LONG" else -1
        gross_pnl = (close_price - order.entry_price) * order.qty * direction
        order.realized_pnl = gross_pnl - order.fees_paid * 2  # 進場+出場兩次手續費
        self.closed_orders.append(order)
        logger.info(f"關閉 {order.symbol} {reason} P&L={order.realized_pnl:.2f}")
    
    def get_portfolio_snapshot(self) -> dict:
        """給前端 dashboard 用"""
        crypto_orders = [o for o in self.open_orders.values() if o.pool == "crypto"]
        stock_orders = [o for o in self.open_orders.values() if o.pool == "stock"]
        return {
            "crypto_pool": {
                "total": self.crypto_pool,
                "available": self._available_capital("crypto"),
                "open_positions": len(crypto_orders),
                "realized_pnl": sum(o.realized_pnl for o in self.closed_orders if o.pool == "crypto"),
                "positions": [self._order_to_dict(o) for o in crypto_orders],
            },
            "stock_pool": {
                "total": self.stock_pool,
                "available": self._available_capital("stock"),
                "open_positions": len(stock_orders),
                "realized_pnl": sum(o.realized_pnl for o in self.closed_orders if o.pool == "stock"),
                "positions": [self._order_to_dict(o) for o in stock_orders],
            },
        }

    def _order_to_dict(self, o: "ExecutionOrder") -> dict:
        tp1 = o.take_profit[0] if o.take_profit else None
        tp2 = o.take_profit[1] if len(o.take_profit) > 1 else None
        notional = o.qty * o.entry_price
        return {
            "order_id": o.order_id,
            "symbol": o.symbol,
            "side": o.side,
            "qty": o.qty,
            "entry_price": o.entry_price,
            "stop_loss": o.stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp1_filled": False,  # TP1 現在是全數平倉，倉位會直接消失
            "status": o.status.value,
            "entry_time": o.submitted_at.isoformat() if o.submitted_at else None,
            "filled_time": o.filled_at.isoformat() if o.filled_at else None,
            "notional_usdt": round(notional, 2),
            "consensus_score": o.consensus_score,
            "contributors": o.contributors,
        }

    async def fetch_binance_balance(self) -> Optional[float]:
        """從 Binance 合約帳戶拉即時 USDT 餘額，更新 crypto_pool"""
        if self.binance is None:
            return None
        try:
            # defaultType=future 時 fetch_balance 直接讀合約錢包
            balance = await self.binance.fetch_balance({"type": "future"})
            usdt = balance.get("USDT", {}).get("free", None)
            if usdt is not None:
                self.crypto_pool = float(usdt)
                logger.info(f"✅ Binance 合約餘額: {usdt:.2f} USDT")
            return usdt
        except Exception as e:
            logger.error(f"Binance 合約餘額拉取失敗: {e}")
            return None

    async def check_tp1_and_close(self):
        """檢查開放倉位，TP1 達到時全部平倉"""
        if self.binance is None:
            return
        for order_id, order in list(self.open_orders.items()):
            if order.pool != "crypto" or not order.take_profit:
                continue
            if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
                continue  # 已平倉
            try:
                ticker = await self.binance.fetch_ticker(order.symbol)
                current_price = ticker["last"]
                tp1 = order.take_profit[0]
                if order.side == "LONG" and current_price >= tp1:
                    await self._execute_full_close(order, current_price, "TP1")
                elif order.side == "SHORT" and current_price <= tp1:
                    await self._execute_full_close(order, current_price, "TP1")
            except Exception as e:
                logger.error(f"TP1 檢查失敗 {order.symbol}: {e}")

    async def _execute_full_close(self, order: "ExecutionOrder", price: float, reason: str = "TP1"):
        """全數平倉並移入 closed_orders"""
        try:
            side = "sell" if order.side == "LONG" else "buy"
            await self.binance.create_market_order(
                order.symbol, side, order.qty, None, {"reduceOnly": True}
            )
            pnl = (price - order.entry_price) * order.qty * (1 if order.side == "LONG" else -1)
            order.realized_pnl += pnl - order.qty * price * self.fee_rate_crypto
            order.status = OrderStatus.FILLED
            self.on_close(order.order_id, price, reason)
            logger.info(f"✅ {reason} 全數平倉 {order.symbol} qty={order.qty} price={price} PnL={pnl:.2f}")
        except Exception as e:
            logger.error(f"{reason} 平倉失敗 {order.symbol}: {e}")
