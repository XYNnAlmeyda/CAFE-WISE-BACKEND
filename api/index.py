from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .routers import (
    admin_router,
    inventory_router,
    sales_router,
    ingredients_router,
    recipes_router,
    waste_router,
    dashboard_router,
    analytics_router,
    activity_router,
    shifts_router,
)

# CafeWise FastAPI Application Architecture — Opening E-Wallet Float Added
app = FastAPI(title="CafeWise API")

# ── CORS ─────────────────────────────────────────────────────────────────────
# CORS_ORIGIN env var: set this in Vercel dashboard to your frontend URL
# e.g. https://houseblend-frontend.vercel.app
_cors_env = os.environ.get("CORS_ORIGIN", "")
_extra_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

_allowed_origins = list(set([
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://192.168.3.188:5173",
    "http://192.168.3.188:5174",
    "https://houseblend-frontend.vercel.app",
] + _extra_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # Also allow any Vercel preview/branch deploy (*.vercel.app)
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(admin_router)
app.include_router(inventory_router)
app.include_router(sales_router)
app.include_router(ingredients_router)
app.include_router(recipes_router)
app.include_router(waste_router)
app.include_router(dashboard_router)
app.include_router(analytics_router)
app.include_router(activity_router)
app.include_router(shifts_router)

@app.get("/")
@app.get("/api")
@app.get("/api/index.py")
def read_root():
    return {"message": "Welcome to the CafeWise Python Backend"}

# ─────────────────────────────────────────────
# Server Startup
# ─────────────────────────────────────────────

import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.index:app", host="127.0.0.1", port=8000, reload=True)