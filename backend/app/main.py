"""FastAPI 应用入口"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import settings
from app.utils.logger import setup_logging, get_logger
from app.models.database import init_db


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    setup_logging(debug=settings.debug)
    logger.info("Starting NewsFeed API", version=settings.app_version)
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down NewsFeed API")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered stock news analysis platform",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
async def root():
    """根路径重定向到 API 文档"""
    return RedirectResponse(url="/docs")


@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "ai_provider": settings.ai_provider,
    }


# Import and include routers after app creation to avoid circular imports
def include_routers():
    """动态导入并注册路由"""
    from app.api import router as api_router
    app.include_router(api_router.router, prefix="/api")


# Include routers
include_routers()
