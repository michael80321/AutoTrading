"""
資料庫模型 — TimescaleDB 相容 (timestamp 為主鍵一部分)
"""
from datetime import datetime
from sqlalchemy import Column, String, Float, Boolean, DateTime, Integer, Text, JSON
from .session import Base


class TradeRecord(Base):
    __tablename__ = "trade_records"

    order_id = Column(String, primary_key=True)
    pool = Column(String(10), nullable=False, index=True)          # crypto / stock
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(5), nullable=False)                        # LONG / SHORT
    qty = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float)
    take_profit = Column(JSON)                                       # list of prices
    realized_pnl = Column(Float, default=0.0)
    fees_paid = Column(Float, default=0.0)
    consensus_score = Column(Float, default=0.0)
    contributors = Column(JSON)                                      # list of bot names
    status = Column(String(20), default="pending")
    submitted_at = Column(DateTime, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime, nullable=True)


class SignalRecord(Base):
    __tablename__ = "signal_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    pool = Column(String(10), nullable=False, index=True)
    bot_id = Column(String(50), nullable=False, index=True)
    bot_name = Column(String(100), nullable=False)
    school = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(5), nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float)
    take_profit = Column(JSON)
    confidence = Column(Float, default=0.5)
    rationale = Column(Text)


class EvolutionEvent(Base):
    __tablename__ = "evolution_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    pool = Column(String(10), nullable=False, index=True)
    bot_id = Column(String(50), nullable=False)
    bot_name = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)    # promote_breed / demote_sandbox / retire
    note = Column(Text)
    metrics_snapshot = Column(JSON)


class BotPerformance(Base):
    __tablename__ = "bot_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    pool = Column(String(10), nullable=False, index=True)
    bot_id = Column(String(50), nullable=False, index=True)
    bot_name = Column(String(100), nullable=False)
    school = Column(String(50), nullable=False)
    win_rate = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    composite_score = Column(Float, default=0.0)
    dynamic_weight = Column(Float, default=1.0)
    total_trades = Column(Integer, default=0)
    realized_pnl = Column(Float, default=0.0)
