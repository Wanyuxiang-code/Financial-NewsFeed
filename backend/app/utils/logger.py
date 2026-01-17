"""结构化日志 + run_id 追踪"""
import logging
import sys
from typing import Optional
from contextvars import ContextVar
from uuid import UUID, uuid4

import structlog


# Context variable for run_id tracing
current_run_id: ContextVar[Optional[UUID]] = ContextVar("current_run_id", default=None)


def get_run_id() -> Optional[UUID]:
    """获取当前 run_id"""
    return current_run_id.get()


def set_run_id(run_id: Optional[UUID] = None) -> UUID:
    """设置当前 run_id，如果未提供则生成新的"""
    if run_id is None:
        run_id = uuid4()
    current_run_id.set(run_id)
    return run_id


def add_run_id(logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
    """Structlog processor: 添加 run_id 到日志"""
    run_id = get_run_id()
    if run_id:
        event_dict["run_id"] = str(run_id)
    return event_dict


def setup_logging(debug: bool = False) -> None:
    """配置 structlog 日志"""
    
    # 配置标准库 logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if debug else logging.INFO,
    )
    
    # 配置 structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            add_run_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """获取命名 logger"""
    return structlog.get_logger(name)
