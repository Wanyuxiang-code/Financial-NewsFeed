"""Watchlist API endpoints - CRUD for stock watchlist"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import WatchlistItemCreate, WatchlistItemUpdate, WatchlistItemResponse
from app.models import crud

router = APIRouter()


@router.get("", response_model=List[WatchlistItemResponse])
async def get_watchlist(
    sector: Optional[str] = None,
    priority: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取关注列表，支持按板块和优先级过滤"""
    items = await crud.get_watchlist(db, sector=sector, priority=priority)
    return items


@router.get("/{ticker}", response_model=WatchlistItemResponse)
async def get_watchlist_item(ticker: str, db: AsyncSession = Depends(get_db)):
    """获取单个股票详情"""
    item = await crud.get_watchlist_item(db, ticker=ticker.upper())
    if not item:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    return item


@router.post("", response_model=WatchlistItemResponse, status_code=201)
async def create_watchlist_item(
    item: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db)
):
    """添加新股票到关注列表"""
    existing = await crud.get_watchlist_item(db, ticker=item.ticker.upper())
    if existing:
        raise HTTPException(status_code=400, detail=f"Ticker {item.ticker} already exists")
    return await crud.create_watchlist_item(db, item)


@router.put("/{ticker}", response_model=WatchlistItemResponse)
async def update_watchlist_item(
    ticker: str,
    item: WatchlistItemUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新股票信息（thesis/risk_tags/priority等）"""
    updated = await crud.update_watchlist_item(db, ticker=ticker.upper(), item=item)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    return updated


@router.delete("/{ticker}", status_code=204)
async def delete_watchlist_item(ticker: str, db: AsyncSession = Depends(get_db)):
    """从关注列表删除股票"""
    deleted = await crud.delete_watchlist_item(db, ticker=ticker.upper())
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
