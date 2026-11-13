from app.routers.chat import router as chat_router
from app.routers.dashboard import router as dashboard_router
from app.routers.modelfile import router as modelfile_router
from app.routers.proxy import router as proxy_router
from app.routers.terminal import router as terminal_router

__all__ = [
    "dashboard_router",
    "chat_router",
    "terminal_router",
    "modelfile_router",
    "proxy_router",
]
