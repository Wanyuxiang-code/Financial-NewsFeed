"""Tests for deduplicator"""
import pytest
from datetime import datetime

from app.collectors.base import RawNewsData
from app.utils.deduplicator import Deduplicator


@pytest.fixture
def deduplicator():
    return Deduplicator(similarity_threshold=0.85)


@pytest.fixture
def sample_news_items():
    """Sample news items for testing"""
    return [
        RawNewsData(
            source="finnhub",
            source_type="news",
            url="https://example.com/news/1?utm_source=twitter&ref=123",
            title="NVIDIA Reports Record Q4 Revenue of $22 Billion",
            published_at=datetime(2024, 1, 15, 10, 0),
            tickers=["NVDA"]
        ),
        RawNewsData(
            source="finnhub",
            source_type="news",
            url="https://example.com/news/1",  # Same URL without tracking
            title="NVIDIA Reports Record Q4 Revenue of $22 Billion",
            published_at=datetime(2024, 1, 15, 10, 0),
            tickers=["NVDA"]
        ),
        RawNewsData(
            source="polygon",
            source_type="news",
            url="https://other.com/nvda-q4",
            title="NVIDIA Q4 Revenue Hits Record $22B",  # Similar but different
            published_at=datetime(2024, 1, 15, 10, 30),
            tickers=["NVDA"]
        ),
        RawNewsData(
            source="finnhub",
            source_type="news",
            url="https://example.com/news/2",
            title="AMD Announces New GPU Architecture",  # Different news
            published_at=datetime(2024, 1, 15, 11, 0),
            tickers=["AMD"]
        ),
    ]


class TestDeduplicator:
    """Tests for Deduplicator"""
    
    def test_canonicalize_url(self, deduplicator):
        """Test URL canonicalization"""
        url = "https://Example.com/News/Article?utm_source=twitter&ref=123&page=1"
        canonical = deduplicator.canonicalize_url(url)
        
        assert "utm_source" not in canonical
        assert "ref" not in canonical
        assert "page=1" in canonical
        assert "example.com" in canonical.lower()
    
    def test_normalize_title(self, deduplicator):
        """Test title normalization"""
        title = "NVIDIA Reports Record Q4 Revenue!!!"
        normalized = deduplicator.normalize_title(title)
        
        assert normalized == "nvidia reports record q4 revenue"
        assert "!" not in normalized
    
    def test_compute_content_hash(self, deduplicator, sample_news_items):
        """Test content hash computation"""
        item1 = sample_news_items[0]
        item2 = sample_news_items[1]
        
        hash1 = deduplicator.compute_content_hash(item1)
        hash2 = deduplicator.compute_content_hash(item2)
        
        # Same title + date + source should produce same hash
        assert hash1 == hash2
    
    def test_url_dedup(self, deduplicator, sample_news_items):
        """Test URL deduplication"""
        result = deduplicator.deduplicate(sample_news_items)
        
        # Should remove the duplicate URL
        urls = [item.url for item in result.kept_items]
        unique_urls = set(deduplicator.canonicalize_url(u) for u in urls)
        
        assert len(unique_urls) == len(result.kept_items)
    
    def test_dedup_preserves_unique_news(self, deduplicator, sample_news_items):
        """Test that unique news items are preserved"""
        result = deduplicator.deduplicate(sample_news_items)
        
        # AMD news should always be preserved (it's unique)
        amd_news = [item for item in result.kept_items if "AMD" in item.tickers]
        assert len(amd_news) == 1
    
    def test_dedup_result_statistics(self, deduplicator, sample_news_items):
        """Test dedup result statistics"""
        result = deduplicator.deduplicate(sample_news_items)
        
        assert result.removed_count == len(sample_news_items) - len(result.kept_items)
        assert result.removed_count >= 0
    
    def test_empty_input(self, deduplicator):
        """Test with empty input"""
        result = deduplicator.deduplicate([])
        
        assert result.kept_items == []
        assert result.removed_count == 0
