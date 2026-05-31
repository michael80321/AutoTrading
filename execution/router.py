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
        self._crypto_pool_last_known: float | None = None  # 最後一次從交易所拉到的真實餘額
        self.stock_pool = stock_pool_usd
        self.halted: bool = False  # 熔斷開關：True 時拒絕所有新訂單
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
        """從共識引擎接收 ConsensusResult，提交訂單"""
        if self.halted:
            logger.warning("熔斷中，拒絕新訂單")
            return None

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
            # _submit_binance adds to open_orders directly (to prevent orphan on SL failure).
            # _submit_ibkr paper path sets status=FILLED — preserve it.
            if order.order_id not in self.open_orders:
                if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                    order.status = OrderStatus.SUBMITTED
                if order.submitted_at is None:
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
            # 精度處理：只在首次或市場未快取時呼叫 load_markets
            if not self.binance.markets:
                await self.binance.load_markets()
            market = self.binance.markets.get(order.symbol) or \
                     self.binance.markets.get(order.symbol.replace("USDT", "/USDT"))
            qty = order.qty
            if market:
                precision = market.get("precision", {}).get("amount", 3)
                qty = round(order.qty, precision)
            if qty <= 0:
                logger.warning(f"{order.symbol} 取整後數量為 0，跳過下單")
                order.status = OrderStatus.REJECTED
                return False
            order.qty = qty

            # 1. 市價開倉 — 成功後立即標記，避免孤兒倉位
            await self.binance.create_market_order(order.symbol, side, qty)
            order.fees_paid = qty * order.entry_price * self.fee_rate_crypto
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.now()
            self.open_orders[order.order_id] = order  # 先入帳，SL/TP 失敗也能追蹤

            # 2. 止損單 STOP_MARKET
            try:
                await self.binance.create_order(
                    order.symbol, "STOP_MARKET", opp_side, qty, None,
                    {"stopPrice": order.stop_loss, "reduceOnly": True},
                )
            except Exception as e:
                logger.error(f"⚠️ {order.symbol} SL 掛單失敗，倉位已開但無止損: {e}")

            # 3. 止盈單 TAKE_PROFIT_MARKET
            if order.take_profit:
                try:
                    await self.binance.create_order(
                        order.symbol, "TAKE_PROFIT_MARKET", opp_side, qty, None,
                        {"stopPrice": order.take_profit[0], "reduceOnly": True},
                    )
                except Exception as e:
                    logger.error(f"⚠️ {order.symbol} TP 掛單失敗，倉位已開但無止盈: {e}")

            logger.info(f"✅ 合約下單 {order.symbol} {order.side} qty={qty} "
                        f"SL={order.stop_loss} TP={order.take_profit[0] if order.take_profit else 'N/A'}")
            return True
        except Exception as e:
            logger.error(f"Binance 合約下單失敗: {e}")
            order.status = OrderStatus.REJECTED
            return False
    
    async def _submit_ibkr(self, order: ExecutionOrder) -> bool:
        """提交至 IBKR — 若無連線則以虛擬盤模擬成交"""
        if self.ibkr is None:
            # 虛擬盤：立即以進場價模擬成交
            order.status = OrderStatus.FILLED
            order.filled_at = datetime.now()
            order.fees_paid = order.qty * order.entry_price * self.fee_rate_stock
            tp_str = f"{order.take_profit[0]:.2f}" if order.take_profit else "N/A"
            logger.info(f"[PAPER] 美股 {order.symbol} {order.side} qty={order.qty:.4f} "
                        f"entry={order.entry_price:.2f} SL={order.stop_loss:.2f} TP={tp_str}")
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

    async def check_stock_paper_sl_tp(self, market_data: dict) -> None:
        """虛擬盤：每根 K 棒檢查美股倉位 SL/TP，並更新未實現 P&L"""
        if self.ibkr is not None:
            return  # 真實 IBKR 由交易所處理
        for order_id, order in list(self.open_orders.items()):
            if order.pool != "stock" or order.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                continue
            df = market_data.get(order.symbol)
            if df is None or len(df) == 0:
                continue
            latest_high = float(df["high"].iloc[-1])
            latest_low = float(df["low"].iloc[-1])

            # 檢查 SL（用 low/high 而非 close，模擬日內觸及）
            sl_hit = (order.side == "LONG" and latest_low <= order.stop_loss) or \
                     (order.side == "SHORT" and latest_high >= order.stop_loss)
            tp_hit = order.take_profit and (
                (order.side == "LONG" and latest_high >= order.take_profit[0]) or
                (order.side == "SHORT" and latest_low <= order.take_profit[0])
            )

            if sl_hit:
                close_price = order.stop_loss
                self.on_close(order_id, close_price, "SL")
                logger.info(f"[PAPER] {order.symbol} SL 觸發 @ {close_price:.2f}")
            elif tp_hit:
                close_price = order.take_profit[0]
                self.on_close(order_id, close_price, "TP1")
                logger.info(f"[PAPER] {order.symbol} TP1 觸發 @ {close_price:.2f}")
    
    def on_fill(self, order_id: str, fill_price: float, fill_qty: float):
        """成交回調"""
        order = self.open_orders.get(order_id)
        if not order:
            return
        order.status = OrderStatus.FILLED if fill_qty >= order.qty else OrderStatus.PARTIALLY_FILLED
        order.filled_at = datetime.now()
    
    def on_close(self, order_id: str, close_price: float, reason: str):
        """部位關閉回調 — 計算 P&L（進場費已在 fees_paid，此處加出場費）"""
        order = self.open_orders.pop(order_id, None)
        if not order:
            return
        direction = 1 if order.side == "LONG" else -1
        gross_pnl = (close_price - order.entry_price) * order.qty * direction
        fee_rate = self.fee_rate_crypto if order.pool == "crypto" else self.fee_rate_stock
        exit_fee = order.qty * close_price * fee_rate
        order.realized_pnl = gross_pnl - order.fees_paid - exit_fee
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
                self._crypto_pool_last_known = float(usdt)
                logger.info(f"✅ Binance 合約餘額: {usdt:.2f} USDT")
            return usdt
        except Exception as e:
            logger.error(f"Binance 合約餘額拉取失敗: {e}")
            # 保留最後已知真實餘額，避免回退到 config 預設值
            if self._crypto_pool_last_known is not None:
                self.crypto_pool = self._crypto_pool_last_known
            return None

    async def _reconcile_exchange_positions(self):
        """對帳：把交易所已平倉的倉位從 open_orders 清除，防止幽靈訂單鎖死資金"""
        if self.binance is None:
            return
        try:
            positions = await self.binance.fetch_positions()
            open_symbols = {p["symbol"] for p in positions if float(p.get("contracts", 0)) != 0}
            for order_id, order in list(self.open_orders.items()):
                if order.pool != "crypto":
                    continue
                ccxt_symbol = order.symbol.replace("USDT", "/USDT:USDT")
                if ccxt_symbol not in open_symbols and order.symbol not in open_symbols:
                    # 交易所已無此倉位（被 SL/TP 成交），視同關閉
                    ticker = await self.binance.fetch_ticker(order.symbol)
                    close_price = ticker["last"]
                    logger.info(f"🔄 對帳：{order.symbol} 交易所已平倉，清除幽靈訂單 @ {close_price:.4f}")
                    self.on_close(order_id, close_price, "EXCHANGE_CLOSE")
        except Exception as e:
            logger.warning(f"對帳失敗（非致命）: {e}")

    async def check_tp1_and_close(self):
        """檢查開放倉位，TP1 達到時全部平倉；同時對帳幽靈倉位"""
        if self.binance is None:
            return
        await self._reconcile_exchange_positions()
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
        """全數平倉並移入 closed_orders — P&L 由 on_close 統一計算"""
        try:
            side = "sell" if order.side == "LONG" else "buy"
            await self.binance.create_market_order(
                order.symbol, side, order.qty, None, {"reduceOnly": True}
            )
            self.on_close(order.order_id, price, reason)
        except Exception as e:
            logger.error(f"{reason} 平倉失敗 {order.symbol}: {e}")
