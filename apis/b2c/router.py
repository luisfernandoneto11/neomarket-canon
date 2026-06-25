"""
B2C Router.

Aggregates all B2C sub-routers under /api/v1/b2c prefix.
"""

from fastapi import APIRouter

from .cart import router as cart_router

router = APIRouter(prefix="/api/v1/b2c", tags=["B2C"])

router.include_router(cart_router)