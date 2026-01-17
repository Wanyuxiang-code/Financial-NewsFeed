"""Jobs API endpoints - pipeline execution and observability"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import PipelineRunResponse, PipelineRunCreate
from app.models import crud
from app.core.pipeline import run_pipeline
from app.utils.logger import get_logger, set_run_id

router = APIRouter()
logger = get_logger(__name__)


@router.post("/run", response_model=PipelineRunResponse, status_code=202)
async def trigger_pipeline_run(
    background_tasks: BackgroundTasks,
    hours_lookback: int = 24,
    tickers: Optional[List[str]] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    手动触发 pipeline 运行
    
    - hours_lookback: 向前查找新闻的小时数
    - tickers: 可选，指定只处理某些股票，不指定则处理全部 watchlist
    
    返回 run_id 用于查询进度
    """
    # Create pipeline run record
    run_id = set_run_id()
    
    pipeline_run = await crud.create_pipeline_run(
        db,
        PipelineRunCreate(
            run_id=run_id,
            status="running",
            started_at=datetime.utcnow()
        )
    )
    
    logger.info(
        "Pipeline run triggered",
        run_id=str(run_id),
        hours_lookback=hours_lookback,
        tickers=tickers
    )
    
    # Run pipeline in background
    background_tasks.add_task(
        run_pipeline,
        run_id=run_id,
        hours_lookback=hours_lookback,
        tickers=tickers
    )
    
    return pipeline_run


@router.get("/{run_id}", response_model=PipelineRunResponse)
async def get_pipeline_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    """查看 pipeline 运行进度和统计"""
    run = await crud.get_pipeline_run(db, run_id=run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Pipeline run {run_id} not found")
    return run


@router.get("", response_model=List[PipelineRunResponse])
async def list_pipeline_runs(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """列出历史 pipeline 运行记录"""
    runs = await crud.get_pipeline_runs(db, status=status, limit=limit, offset=offset)
    return runs
