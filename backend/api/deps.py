"""
FastAPI 依賴注入 — 共用 DualPoolOrchestrator 單例
"""
_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from autotrading.main import DualPoolOrchestrator
        _orchestrator = DualPoolOrchestrator()
        _orchestrator.initialize()
    return _orchestrator
