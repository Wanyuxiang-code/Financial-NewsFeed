"""Main API router - aggregates all sub-routers"""
from fastapi import APIRouter

from app.api import watchlist, news, jobs

router = APIRouter()

# Include sub-routers
router.include_router(watchlist.router, prefix="/watchlist", tags=["Watchlist"])
router.include_router(news.router, prefix="/news", tags=["News"])
router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
