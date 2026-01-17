"""Tests for data collectors"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from app.collectors.base import RawNewsData
from app.collectors.finnhub import FinnhubNewsCollector, FinnhubClient


@pytest.fixture
def sample_finnhub_response():
    """Sample Finnhub API response"""
    return [
        {
            "id": 12345,
            "headline": "NVIDIA Reports Record Q4 Revenue",
            "summary": "NVIDIA announced record quarterly revenue of $22.1 billion.",
            "source": "Reuters",
            "url": "https://example.com/news/nvda-q4",
            "datetime": int(datetime.utcnow().timestamp()),
            "related": "NVDA",
            "category": "company",
            "image": "https://example.com/image.jpg"
        },
        {
            "id": 12346,
            "headline": "Tech Stocks Rally on AI Optimism",
            "summary": "Major tech stocks gained on continued AI investment.",
            "source": "Bloomberg",
            "url": "https://example.com/news/tech-rally",
            "datetime": int(datetime.utcnow().timestamp()),
            "related": "NVDA,AMD,GOOGL",
            "category": "market",
            "image": ""
        }
    ]


class TestFinnhubCollector:
    """Tests for FinnhubNewsCollector"""
    
    @pytest.mark.asyncio
    async def test_parse_news_item(self, sample_finnhub_response):
        """Test parsing of Finnhub news response"""
        collector = FinnhubNewsCollector(api_key="test_key")
        
        item = collector._parse_news_item(sample_finnhub_response[0], "NVDA")
        
        assert item is not None
        assert item.source == "finnhub"
        assert item.source_type == "news"
        assert "NVDA" in item.tickers
        assert item.title == "NVIDIA Reports Record Q4 Revenue"
        assert item.url == "https://example.com/news/nvda-q4"
    
    @pytest.mark.asyncio
    async def test_parse_multiple_tickers(self, sample_finnhub_response):
        """Test parsing news with multiple related tickers"""
        collector = FinnhubNewsCollector(api_key="test_key")
        
        item = collector._parse_news_item(sample_finnhub_response[1], "NVDA")
        
        assert item is not None
        assert "NVDA" in item.tickers
        assert "AMD" in item.tickers
        assert "GOOGL" in item.tickers
    
    @pytest.mark.asyncio
    async def test_collector_attributes(self):
        """Test collector class attributes"""
        collector = FinnhubNewsCollector(api_key="test_key")
        
        assert collector.source == "finnhub"
        assert collector.source_type == "news"
        assert collector.credibility == "medium"


class TestRawNewsData:
    """Tests for RawNewsData dataclass"""
    
    def test_create_raw_news_data(self):
        """Test creating RawNewsData instance"""
        data = RawNewsData(
            source="test",
            source_type="news",
            url="https://example.com",
            title="Test News",
            tickers=["AAPL", "GOOGL"]
        )
        
        assert data.source == "test"
        assert data.source_type == "news"
        assert data.url == "https://example.com"
        assert len(data.tickers) == 2
    
    def test_default_values(self):
        """Test default values for optional fields"""
        data = RawNewsData(
            source="test",
            source_type="news"
        )
        
        assert data.url == ""
        assert data.title == ""
        assert data.tickers == []
        assert data.summary is None
        assert data.published_at is None
