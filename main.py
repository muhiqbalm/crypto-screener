#!/usr/bin/env python3
"""
Crypto Screener - Main Entry Point

Run this script to execute the crypto screener system.
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

# Dependency validation
try:
    import ccxt
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn as sns
except ImportError as e:
    print(f"ERROR: Missing required dependency: {e}")
    print("Please install dependencies using: pip install -r requirements.txt")
    sys.exit(1)

# Import modules using the correct package paths (src.*)
from src.exchange.connector import ExchangeConnector
from src.data.fetcher import MarketDataFetcher
from src.signals.generator import SignalGenerator
from src.signals.ic_weights import ICWeightCalculator
from src.signals.scorer import MultiFactorScorer
from src.ranking.engine import RankingEngine
from src.visualization.dashboard import DashboardBuilder

# Configure logging
log_dir = Path('output/logs')
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / f'crypto_screener_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main execution flow for the crypto screener system."""
    logger.info("=" * 70)
    logger.info("Starting Crypto Screener System")
    logger.info("=" * 70)
    
    # Define symbol list (Binance USDT-M Futures compatible)
    SYMBOLS = [
        'BTC/USDT:USDT',
        'ETH/USDT:USDT',
        'SOL/USDT:USDT',
        'AAVE/USDT:USDT',
        'LINK/USDT:USDT',
        'AVAX/USDT:USDT',
        'DOGE/USDT:USDT'
    ]
    
    logger.info(f"Target symbols: {SYMBOLS}")
    
    try:
        # Stage 1: Connect to exchange
        logger.info("\n" + "=" * 70)
        logger.info("Stage 1: Connecting to exchange")
        logger.info("=" * 70)
        
        connector = ExchangeConnector(exchange_id='binanceusdm')
        connector.connect()
        exchange = connector.get_exchange()
        
        logger.info("[SUCCESS] Exchange connection established")
        
        # Stage 2: Fetch market data
        logger.info("\n" + "=" * 70)
        logger.info("Stage 2: Fetching market data")
        logger.info("=" * 70)
        
        # Binance USDT-M Futures symbol format: 'BTC/USDT:USDT'
        fetcher = MarketDataFetcher(exchange, SYMBOLS)
        market_data = fetcher.fetch_all_data()
        
        logger.info(f"[SUCCESS] Fetched data for {len(market_data)} symbols")
        
        # Stage 3: Generate signals
        logger.info("\n" + "=" * 70)
        logger.info("Stage 3: Generating trading signals")
        logger.info("=" * 70)
        
        signal_gen = SignalGenerator()
        
        # Calculate and normalize all 5 signal factors
        market_data['reversal_signal'] = signal_gen.normalize_signal(
            signal_gen.calculate_reversal_signal(market_data)
        )
        market_data['momentum_signal'] = signal_gen.normalize_signal(
            signal_gen.calculate_momentum_signal(market_data)
        )
        market_data['funding_rate_signal'] = signal_gen.normalize_signal(
            signal_gen.calculate_funding_rate_signal(market_data)
        )
        market_data['sentiment_signal'] = signal_gen.normalize_signal(
            signal_gen.calculate_sentiment_signal(market_data)
        )
        market_data['oi_momentum_signal'] = signal_gen.normalize_signal(
            signal_gen.calculate_oi_momentum_signal(market_data)
        )
        
        logger.info("[SUCCESS] All 5 signals generated and normalized")
        
        # Stage 4: Calculate multi-factor scores
        logger.info("\n" + "=" * 70)
        logger.info("Stage 4: Calculating multi-factor scores")
        logger.info("=" * 70)
        
        ic_calc = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calc)
        
        # Calculate multi-factor score (requires all 5 signal columns)
        market_data['multi_factor_score'] = scorer.calculate_score(market_data)
        
        # Calculate risk-adjusted score (uses atr_percent)
        market_data = scorer.calculate_risk_adjusted_score(market_data)
        
        # Calculate position sizing (uses atr_percent)
        market_data = scorer.calculate_position_sizing(market_data)
        
        # Calculate confidence rate
        market_data = scorer.calculate_confidence_rate(market_data)
        
        # Classify tiers
        market_data['tier'] = scorer.classify_tiers(market_data['multi_factor_score'])
        
        logger.info("[SUCCESS] Multi-factor scores, risk adjustment, and tiers calculated")
        
        # Stage 5: Rank assets
        logger.info("\n" + "=" * 70)
        logger.info("Stage 5: Ranking assets")
        logger.info("=" * 70)
        
        ranker = RankingEngine()
        ranked_data = ranker.rank_assets(market_data)
        
        logger.info("[SUCCESS] Assets ranked")
        logger.info(f"\nTop 3 assets:\n{ranked_data[['symbol', 'multi_factor_score', 'risk_adjusted_score', 'tier', 'rank']].head(3)}")
        
        # Stage 6: Generate dashboard
        logger.info("\n" + "=" * 70)
        logger.info("Stage 6: Generating visualization dashboard")
        logger.info("=" * 70)
        
        dashboard_dir = Path('output/dashboards')
        dashboard_dir.mkdir(parents=True, exist_ok=True)
        
        builder = DashboardBuilder(ranked_data)
        builder.create_dashboard()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = dashboard_dir / f'crypto_screener_dashboard_{timestamp}.png'
        builder.save_dashboard(str(output_path))
        
        logger.info(f"[SUCCESS] Dashboard saved to {output_path}")
        
        logger.info("\n" + "=" * 70)
        logger.info("Crypto Screener System completed successfully!")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"[FAILED] System error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
