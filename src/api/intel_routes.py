"""API Router for real-time intelligence endpoints (Whale Radar & Live News)."""

from fastapi import APIRouter
from src.services.intel_service import intel_service

router = APIRouter(prefix="/api/v1/intel", tags=["Market Intelligence"])


@router.get("/whales")
async def get_whales_intel():
    """Returns real Binance Futures Top Trader Long/Short ratios and recent whale orders."""
    return await intel_service.get_whales_data()


@router.get("/news")
async def get_news_intel():
    """Returns real Crypto Fear & Greed index and live RSS crypto news items."""
    return await intel_service.get_news_data()
