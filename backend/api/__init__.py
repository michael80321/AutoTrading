from .crypto import router as crypto_router
from .stock import router as stock_router
from .system import router as system_router

__all__ = ["crypto_router", "stock_router", "system_router"]
