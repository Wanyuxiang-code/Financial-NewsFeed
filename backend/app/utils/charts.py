"""股票图表生成器 - K线图与价格走势"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

# 延迟导入（避免启动时的依赖问题）
yf = None
mpf = None
plt = None


def _ensure_imports():
    """延迟导入图表依赖"""
    global yf, mpf, plt
    if yf is None:
        try:
            import yfinance as _yf
            import mplfinance as _mpf
            import matplotlib.pyplot as _plt
            yf = _yf
            mpf = _mpf
            plt = _plt
            # 设置中文字体和风格
            plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            plt.style.use('dark_background')
        except ImportError as e:
            logger.warning(f"Chart dependencies not available: {e}")
            return False
    return True


class ChartGenerator:
    """
    股票图表生成器
    
    生成 K 线图和价格走势图，保存为 PNG 文件
    """
    
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or "data/charts")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def generate_price_chart(
        self,
        ticker: str,
        days: int = 30,
        chart_type: str = "candle"
    ) -> Optional[str]:
        """
        生成价格图表
        
        Args:
            ticker: 股票代码
            days: 历史天数
            chart_type: 图表类型 (candle, line, ohlc)
            
        Returns:
            图表文件路径，失败返回 None
        """
        if not _ensure_imports():
            logger.warning("Chart generation skipped - dependencies not available")
            return None
            
        try:
            # 获取股票数据
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date)
            
            if df.empty:
                logger.warning(f"No data available for {ticker}")
                return None
            
            # 生成图表
            filename = f"{ticker}_{days}d_{datetime.now().strftime('%Y%m%d')}.png"
            filepath = self.output_dir / filename
            
            # 使用 mplfinance 生成专业 K 线图
            mc = mpf.make_marketcolors(
                up='#00ff88',      # 上涨绿色
                down='#ff4444',    # 下跌红色
                edge='inherit',
                wick='inherit',
                volume='in',
            )
            
            style = mpf.make_mpf_style(
                marketcolors=mc,
                base_mpf_style='nightclouds',
                gridstyle='-',
                gridcolor='#333333',
                facecolor='#1a1a2e',
                figcolor='#1a1a2e',
            )
            
            # 计算移动平均线
            mav = (5, 20) if days >= 20 else (5,) if days >= 5 else None
            
            # 获取公司信息
            info = stock.info
            company_name = info.get('shortName', ticker)
            current_price = df['Close'].iloc[-1] if len(df) > 0 else 0
            price_change = ((df['Close'].iloc[-1] / df['Close'].iloc[0]) - 1) * 100 if len(df) > 1 else 0
            
            # 生成图表
            fig, axes = mpf.plot(
                df,
                type=chart_type,
                style=style,
                title=f'\n{ticker} - {company_name}\n${current_price:.2f} ({price_change:+.1f}% in {days}d)',
                ylabel='Price ($)',
                volume=True,
                mav=mav,
                figsize=(10, 6),
                returnfig=True,
                panel_ratios=(3, 1),
            )
            
            # 保存图表
            fig.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
            plt.close(fig)
            
            logger.info(f"Chart generated: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"Failed to generate chart for {ticker}: {e}")
            return None
    
    def generate_mini_chart(
        self,
        ticker: str,
        days: int = 5
    ) -> Optional[str]:
        """
        生成迷你价格走势图（用于嵌入摘要）
        
        Args:
            ticker: 股票代码
            days: 历史天数
            
        Returns:
            图表文件路径
        """
        if not _ensure_imports():
            return None
            
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date)
            
            if df.empty or len(df) < 2:
                return None
            
            # 生成迷你图
            filename = f"{ticker}_mini_{datetime.now().strftime('%Y%m%d')}.png"
            filepath = self.output_dir / filename
            
            fig, ax = plt.subplots(figsize=(4, 1.5), facecolor='#1a1a2e')
            ax.set_facecolor('#1a1a2e')
            
            # 判断涨跌
            is_up = df['Close'].iloc[-1] >= df['Close'].iloc[0]
            color = '#00ff88' if is_up else '#ff4444'
            
            # 绘制价格线
            ax.plot(df.index, df['Close'], color=color, linewidth=2)
            ax.fill_between(df.index, df['Close'], alpha=0.3, color=color)
            
            # 隐藏坐标轴
            ax.set_xticks([])
            ax.set_yticks([])
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.spines['left'].set_visible(False)
            
            # 添加价格标注
            current = df['Close'].iloc[-1]
            change = ((current / df['Close'].iloc[0]) - 1) * 100
            ax.text(
                0.02, 0.95, f'${current:.2f}',
                transform=ax.transAxes,
                color='white',
                fontsize=10,
                fontweight='bold',
                va='top'
            )
            ax.text(
                0.98, 0.95, f'{change:+.1f}%',
                transform=ax.transAxes,
                color=color,
                fontsize=9,
                fontweight='bold',
                va='top',
                ha='right'
            )
            
            fig.tight_layout(pad=0.1)
            fig.savefig(filepath, dpi=100, bbox_inches='tight', facecolor='#1a1a2e')
            plt.close(fig)
            
            return str(filepath)
            
        except Exception as e:
            logger.error(f"Failed to generate mini chart for {ticker}: {e}")
            return None
    
    def generate_batch_charts(
        self,
        tickers: List[str],
        days: int = 30
    ) -> Dict[str, Optional[str]]:
        """
        批量生成图表
        
        Args:
            tickers: 股票代码列表
            days: 历史天数
            
        Returns:
            {ticker: filepath} 映射
        """
        results = {}
        for ticker in tickers:
            results[ticker] = self.generate_price_chart(ticker, days)
        return results


# 单例实例
_chart_generator = None


def get_chart_generator() -> ChartGenerator:
    """获取图表生成器单例"""
    global _chart_generator
    if _chart_generator is None:
        _chart_generator = ChartGenerator()
    return _chart_generator
