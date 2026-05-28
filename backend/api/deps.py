"""
FastAPI 依賴注入 — 共用 DualPoolOrchestrator 單例
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from functools import lru_cache

# 延遲初始化,避免啟動時就連接 broker
_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from main import DualPoolOrchestrator
        _orchestrator = DualPoolOrchestrator()
        _orchestrator.initialize()
    return _orchestrator
