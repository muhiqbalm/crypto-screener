#!/usr/bin/env python3
"""
Script to reorganize the crypto screener project structure.

This script will:
1. Create new directory structure
2. Move test files to tests/ directory
3. Move demo files to demos/ directory
4. Move documentation to docs/ directory
5. Create output directories for logs and dashboards
"""

import os
import shutil
from pathlib import Path

def create_directory_structure():
    """Create the new directory structure."""
    directories = [
        'src/exchange',
        'src/data',
        'src/signals',
        'src/ranking',
        'src/visualization',
        'src/utils',
        'tests/test_exchange',
        'tests/test_data',
        'tests/test_signals',
        'tests/test_ranking',
        'tests/test_visualization',
        'demos',
        'docs',
        'output/logs',
        'output/dashboards'
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        # Create __init__.py for Python packages
        if directory.startswith('src/') or directory.startswith('tests/'):
            init_file = Path(directory) / '__init__.py'
            if not init_file.exists():
                init_file.write_text('"""Package initialization."""\n')
    
    print("✓ Directory structure created")

def move_test_files():
    """Move test files to tests/ directory."""
    test_files = [
        ('test_exchange_connector.py', 'tests/test_exchange/'),
        ('test_market_data_fetcher.py', 'tests/test_data/'),
        ('test_fetch_all_data.py', 'tests/test_data/'),
        ('test_fetch_all_data_integration.py', 'tests/test_data/'),
        ('test_signal_generator.py', 'tests/test_signals/'),
        ('test_ic_weight_calculator.py', 'tests/test_signals/'),
        ('test_multi_factor_scorer.py', 'tests/test_signals/'),
        ('test_ranking_engine.py', 'tests/test_ranking/'),
        ('test_multi_factor_panel.py', 'tests/test_visualization/'),
        ('test_multi_factor_panel_unit.py', 'tests/test_visualization/'),
        ('test_funding_rate_panel.py', 'tests/test_visualization/'),
        ('test_funding_rate_panel_unit.py', 'tests/test_visualization/'),
        ('test_long_short_ratio_panel.py', 'tests/test_visualization/'),
        ('test_dashboard_builder.py', 'tests/test_visualization/'),
        ('test_dashboard_integration.py', 'tests/test_visualization/'),
        ('test_dashboard_visual.py', 'tests/test_visualization/'),
        ('test_main_function.py', 'tests/'),
        ('test_main_requirements.py', 'tests/'),
        ('test_error_handling.py', 'tests/'),
    ]
    
    for source, dest_dir in test_files:
        if os.path.exists(source):
            dest = os.path.join(dest_dir, source)
            shutil.move(source, dest)
            print(f"  Moved {source} → {dest}")
    
    # Move test output images
    for file in Path('.').glob('test_*.png'):
        dest = Path('output/dashboards') / file.name
        shutil.move(str(file), str(dest))
        print(f"  Moved {file.name} → output/dashboards/")
    
    print("✓ Test files moved")

def move_demo_files():
    """Move demo files to demos/ directory."""
    for file in Path('.').glob('demo_*.py'):
        dest = Path('demos') / file.name
        shutil.move(str(file), str(dest))
        print(f"  Moved {file.name} → demos/")
    
    print("✓ Demo files moved")

def move_documentation():
    """Move documentation files to docs/ directory."""
    doc_files = [
        'ERROR_HANDLING_SUMMARY.md',
        'TASK_2.3_SUMMARY.md',
        'TASK_3.4_SUMMARY.md',
        'TASK_3.5_SUMMARY.md',
        'TASK_4.1_SUMMARY.md',
        'TASK_6.1_SUMMARY.md',
        'TASK_6.3_SUMMARY.md',
        'TASK_6.5_SUMMARY.md',
        'RESTRUCTURE_PLAN.md'
    ]
    
    for file in doc_files:
        if os.path.exists(file):
            dest = os.path.join('docs', file)
            shutil.move(file, dest)
            print(f"  Moved {file} → docs/")
    
    print("✓ Documentation moved")

def move_logs():
    """Move log files to output/logs/ directory."""
    for file in Path('.').glob('crypto_screener_*.log'):
        dest = Path('output/logs') / file.name
        shutil.move(str(file), str(dest))
    
    print("✓ Log files moved")

def move_output_images():
    """Move output dashboard images."""
    if os.path.exists('sample_dashboard.png'):
        shutil.move('sample_dashboard.png', 'output/dashboards/sample_dashboard.png')
        print("  Moved sample_dashboard.png → output/dashboards/")
    
    print("✓ Output images moved")

def update_gitignore():
    """Update .gitignore with new structure."""
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
pip-wheel-metadata/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual Environment
venv/
env/
ENV/
env.bak/
venv.bak/

# PyCharm
.idea/

# VS Code
.vscode/

# Jupyter Notebook
.ipynb_checkpoints

# pytest
.pytest_cache/
.coverage
htmlcov/
*.cover
.hypothesis/

# Output directories
output/logs/*.log
output/dashboards/*.png
!output/dashboards/sample_dashboard.png

# OS
.DS_Store
Thumbs.db
*.swp
*.swo
*~

# Environment variables
.env
.env.local

# Temporary files
*.tmp
*.bak
*.backup
"""
    
    with open('.gitignore', 'w') as f:
        f.write(gitignore_content)
    
    print("✓ .gitignore updated")

def create_main_entry_point():
    """Create main.py as the entry point."""
    main_content = """#!/usr/bin/env python3
\"\"\"
Crypto Screener - Main Entry Point

Run this script to execute the crypto screener system.
\"\"\"

import sys
import logging
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

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

# Import modules
from exchange.connector import ExchangeConnector
from data.fetcher import MarketDataFetcher
from signals.generator import SignalGenerator
from signals.ic_weights import ICWeightCalculator
from signals.scorer import MultiFactorScorer
from ranking.engine import RankingEngine
from visualization.dashboard import DashboardBuilder

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
    \"\"\"Main execution flow for the crypto screener system.\"\"\"
    logger.info("=" * 70)
    logger.info("Starting Crypto Screener System")
    logger.info("=" * 70)
    
    # Define symbol list
    SYMBOLS = [
        'BTC/USDT:USDT',
        'ETH/USDT:USDT',
        'ZEC/USDT:USDT',
        'TAO/USDT:USDT',
        'TON/USDT:USDT',
        'AAVE/USDT:USDT',
        'SOL/USDT:USDT'
    ]
    
    logger.info(f"Target symbols: {SYMBOLS}")
    
    try:
        # Stage 1: Connect to exchange
        logger.info("\\n" + "=" * 70)
        logger.info("Stage 1: Connecting to exchange")
        logger.info("=" * 70)
        
        connector = ExchangeConnector(exchange_id='binanceusdm')
        connector.connect()
        exchange = connector.get_exchange()
        
        logger.info("[SUCCESS] Exchange connection established")
        
        # Stage 2: Fetch market data
        logger.info("\\n" + "=" * 70)
        logger.info("Stage 2: Fetching market data")
        logger.info("=" * 70)
        
        fetcher = MarketDataFetcher(exchange, SYMBOLS)
        market_data = fetcher.fetch_all_data()
        
        logger.info(f"[SUCCESS] Fetched data for {len(market_data)} symbols")
        
        # Stage 3: Generate signals
        logger.info("\\n" + "=" * 70)
        logger.info("Stage 3: Generating trading signals")
        logger.info("=" * 70)
        
        signal_gen = SignalGenerator()
        market_data['reversal_signal'] = signal_gen.calculate_reversal_signal(market_data)
        market_data['momentum_signal'] = signal_gen.calculate_momentum_signal(market_data)
        
        market_data['reversal_signal'] = signal_gen.normalize_signal(market_data['reversal_signal'])
        market_data['momentum_signal'] = signal_gen.normalize_signal(market_data['momentum_signal'])
        
        logger.info("[SUCCESS] Signals generated and normalized")
        
        # Stage 4: Calculate multi-factor scores
        logger.info("\\n" + "=" * 70)
        logger.info("Stage 4: Calculating multi-factor scores")
        logger.info("=" * 70)
        
        ic_calc = ICWeightCalculator()
        scorer = MultiFactorScorer(ic_calc)
        
        market_data['multi_factor_score'] = scorer.calculate_score(market_data)
        market_data['tier'] = scorer.classify_tiers(market_data['multi_factor_score'])
        
        logger.info("[SUCCESS] Multi-factor scores calculated")
        
        # Stage 5: Rank assets
        logger.info("\\n" + "=" * 70)
        logger.info("Stage 5: Ranking assets")
        logger.info("=" * 70)
        
        ranker = RankingEngine()
        ranked_data = ranker.rank_assets(market_data)
        
        logger.info("[SUCCESS] Assets ranked")
        logger.info(f"\\nTop 3 assets:\\n{ranked_data[['symbol', 'multi_factor_score', 'tier', 'rank']].head(3)}")
        
        # Stage 6: Generate dashboard
        logger.info("\\n" + "=" * 70)
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
        
        logger.info("\\n" + "=" * 70)
        logger.info("Crypto Screener System completed successfully!")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"[FAILED] System error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
"""
    
    with open('main.py', 'w') as f:
        f.write(main_content)
    
    print("✓ main.py created")

def main():
    """Run the reorganization."""
    print("\n" + "=" * 70)
    print("CRYPTO SCREENER PROJECT REORGANIZATION")
    print("=" * 70 + "\n")
    
    print("Step 1: Creating directory structure...")
    create_directory_structure()
    
    print("\nStep 2: Moving test files...")
    move_test_files()
    
    print("\nStep 3: Moving demo files...")
    move_demo_files()
    
    print("\nStep 4: Moving documentation...")
    move_documentation()
    
    print("\nStep 5: Moving log files...")
    move_logs()
    
    print("\nStep 6: Moving output images...")
    move_output_images()
    
    print("\nStep 7: Updating .gitignore...")
    update_gitignore()
    
    print("\nStep 8: Creating main.py entry point...")
    create_main_entry_point()
    
    print("\n" + "=" * 70)
    print("REORGANIZATION COMPLETE!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Review the new structure in RESTRUCTURE_PLAN.md")
    print("2. The modular source files are already created in src/")
    print("3. Run: py main.py (to use the new structure)")
    print("4. Or run: py crypto_screener.py (to use the old monolithic file)")
    print("\nNote: crypto_screener.py is kept for backward compatibility")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
