"""Router modules for the API."""

from .admin import router as admin_router
from .inventory import router as inventory_router
from .sales import router as sales_router
from .ingredients import router as ingredients_router
from .recipes import router as recipes_router
from .waste import router as waste_router
from .dashboard import router as dashboard_router
from .analytics import router as analytics_router
from .activity import router as activity_router
from .shifts import router as shifts_router

__all__ = [
    "admin_router",
    "inventory_router",
    "sales_router",
    "ingredients_router",
    "recipes_router",
    "waste_router",
    "dashboard_router",
    "analytics_router",
    "activity_router",
    "shifts_router",
]
