"""CLI 入口 - 手动运行 Pipeline"""
import asyncio
import argparse
from datetime import datetime

from app.core.pipeline import run_pipeline
from app.models.database import init_db, close_db
from app.utils.logger import setup_logging, get_logger, set_run_id
from app.config import settings

logger = get_logger(__name__)


async def main_async(args):
    """异步主函数"""
    # 初始化日志
    setup_logging(debug=args.debug)
    
    # 初始化数据库
    await init_db()
    logger.info("Database initialized")
    
    # 设置 run_id
    run_id = set_run_id()
    
    # 解析 tickers
    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    
    logger.info(
        "Starting pipeline",
        run_id=str(run_id),
        hours_lookback=args.hours,
        tickers=tickers
    )
    
    # 运行 Pipeline
    try:
        digest = await run_pipeline(
            run_id=run_id,
            hours_lookback=args.hours,
            tickers=tickers,
            limit_per_ticker=args.limit
        )
        
        # 打印结果摘要
        print("\n" + "=" * 60)
        print("[PIPELINE COMPLETED]")
        print("=" * 60)
        print(f"Run ID: {digest.run_id}")
        print(f"Window: {digest.window_start} - {digest.window_end}")
        print(f"Total collected: {digest.total_collected}")
        print(f"After dedup: {digest.total_after_dedup}")
        print(f"Analyzed: {digest.total_analyzed} success, {digest.total_failed} failed")
        
        if digest.items:
            print("\n[TOP NEWS]")
            for i, item in enumerate(digest.high_impact_items[:5], 1):
                impact = item.analysis.impact_direction if item.analysis else "N/A"
                print(f"  {i}. [{impact.upper()}] {item.news.title[:60]}...")
        
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise
    finally:
        # 关闭数据库连接
        await close_db()


def main():
    """CLI 入口点"""
    parser = argparse.ArgumentParser(
        description="NewsFeed Pipeline CLI - 股票新闻 AI 分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 运行完整 Pipeline（过去 24 小时）
  python -m app.cli

  # 指定时间范围
  python -m app.cli --hours 48

  # 只处理特定股票
  python -m app.cli --tickers NVDA,GOOGL,TSM

  # 调试模式
  python -m app.cli --debug
        """
    )
    
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="向前查找新闻的小时数 (default: 24)"
    )
    
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="逗号分隔的股票代码列表，不指定则处理全部 watchlist"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制每只股票分析的新闻数量 (default: 无限制)"
    )
    
    args = parser.parse_args()
    
    # 运行
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
