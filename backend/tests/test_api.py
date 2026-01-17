"""Tests for REST API endpoints"""
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime

from app.main import app
from app.models.database import init_db, Base, engine


@pytest.fixture(autouse=True)
async def setup_database():
    """Setup test database"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Async HTTP client for testing"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    """Tests for health check endpoint"""
    
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test health check returns 200"""
        response = await client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestWatchlistAPI:
    """Tests for watchlist API endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_empty_watchlist(self, client):
        """Test getting empty watchlist"""
        response = await client.get("/api/watchlist")
        
        assert response.status_code == 200
        assert response.json() == []
    
    @pytest.mark.asyncio
    async def test_create_watchlist_item(self, client):
        """Test creating a watchlist item"""
        item_data = {
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "thesis": "AI infrastructure leader",
            "priority": 1,
            "sector": "AI基础设施"
        }
        
        response = await client.post("/api/watchlist", json=item_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["ticker"] == "NVDA"
        assert data["company_name"] == "NVIDIA Corporation"
    
    @pytest.mark.asyncio
    async def test_create_duplicate_ticker(self, client):
        """Test creating duplicate ticker returns error"""
        item_data = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
        }
        
        # Create first
        await client.post("/api/watchlist", json=item_data)
        
        # Try to create duplicate
        response = await client.post("/api/watchlist", json=item_data)
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_get_watchlist_item(self, client):
        """Test getting a specific watchlist item"""
        # Create item first
        item_data = {
            "ticker": "GOOGL",
            "company_name": "Alphabet Inc.",
        }
        await client.post("/api/watchlist", json=item_data)
        
        # Get item
        response = await client.get("/api/watchlist/GOOGL")
        
        assert response.status_code == 200
        assert response.json()["ticker"] == "GOOGL"
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_item(self, client):
        """Test getting nonexistent item returns 404"""
        response = await client.get("/api/watchlist/NOTEXIST")
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_update_watchlist_item(self, client):
        """Test updating a watchlist item"""
        # Create item first
        item_data = {
            "ticker": "TSM",
            "company_name": "Taiwan Semiconductor",
        }
        await client.post("/api/watchlist", json=item_data)
        
        # Update item
        update_data = {
            "thesis": "Advanced node monopoly",
            "priority": 1
        }
        response = await client.put("/api/watchlist/TSM", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["thesis"] == "Advanced node monopoly"
        assert data["priority"] == 1
    
    @pytest.mark.asyncio
    async def test_delete_watchlist_item(self, client):
        """Test deleting a watchlist item"""
        # Create item first
        item_data = {
            "ticker": "AMD",
            "company_name": "AMD Inc.",
        }
        await client.post("/api/watchlist", json=item_data)
        
        # Delete item
        response = await client.delete("/api/watchlist/AMD")
        
        assert response.status_code == 204
        
        # Verify deleted
        response = await client.get("/api/watchlist/AMD")
        assert response.status_code == 404


class TestJobsAPI:
    """Tests for jobs API endpoints"""
    
    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client):
        """Test listing jobs when none exist"""
        response = await client.get("/api/jobs")
        
        assert response.status_code == 200
        assert response.json() == []
