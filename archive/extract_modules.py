#!/usr/bin/env python3
"""
Script to extract classes from crypto_screener.py into modular files.
"""

import re
from pathlib import Path

def read_file(filepath):
    """Read file content."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(filepath, content):
    """Write content to file."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def extract_class(content, class_name, start_line, end_line=None):
    """Extract a class from content."""
    lines = content.split('\n')
    
    # Find class start
    class_start = None
    for i, line in enumerate(lines):
        if f'class {class_name}:' in line:
            class_start = i
            break
    
    if class_start is None:
        return None
    
    # Find class end (next class or end of file)
    class_end = len(lines)
    for i in range(class_start + 1, len(lines)):
        if lines[i].startswith('class ') and ':' in lines[i]:
            class_end = i
            break
    
    # Extract class lines
    class_lines = lines[class_start:class_end]
    
    # Remove trailing empty lines
    while class_lines and not class_lines[-1].strip():
        class_lines.pop()
    
    return '\n'.join(class_lines)

def create_data_fetcher():
    """Create src/data/fetcher.py"""
    content = read_file('crypto_screener.py')
    
    class_code = extract_class(content, 'MarketDataFetcher', 131)
    
    module_content = '''"""
Market Data Fetcher Module

Fetches market data for perpetual futures contracts from exchanges.
"""

import logging
import random
import ccxt
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


''' + class_code + '\n'
    
    write_file('src/data/fetcher.py', module_content)
    print("✓ Created src/data/fetcher.py")

def create_signal_generator():
    """Create src/signals/generator.py"""
    content = read_file('crypto_screener.py')
    
    class_code = extract_class(content, 'SignalGenerator', 361)
    
    module_content = '''"""
Signal Generator Module

Generates trading signals from market data.
"""

import logging
import random
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


''' + class_code + '\n'
    
    write_file('src/signals/generator.py', module_content)
    print("✓ Created src/signals/generator.py")

def create_ic_weights():
    """Create src/signals/ic_weights.py"""
    content = read_file('crypto_screener.py')
    
    class_code = extract_class(content, 'ICWeightCalculator', 518)
    
    module_content = '''"""
IC Weight Calculator Module

Manages Information Coefficient (IC) weights for trading signals.
"""

import logging

logger = logging.getLogger(__name__)


''' + class_code + '\n'
    
    write_file('src/signals/ic_weights.py', module_content)
    print("✓ Created src/signals/ic_weights.py")

def create_scorer():
    """Create src/signals/scorer.py"""
    content = read_file('crypto_screener.py')
    
    class_code = extract_class(content, 'MultiFactorScorer', 584)
    
    module_content = '''"""
Multi-Factor Scorer Module

Combines multiple trading signals into a multi-factor score.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)


''' + class_code + '\n'
    
    write_file('src/signals/scorer.py', module_content)
    print("✓ Created src/signals/scorer.py")

def create_ranking_engine():
    """Create src/ranking/engine.py"""
    content = read_file('crypto_screener.py')
    
    class_code = extract_class(content, 'RankingEngine', 707)
    
    module_content = '''"""
Ranking Engine Module

Ranks assets by multi-factor score.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)


''' + class_code + '\n'
    
    write_file('src/ranking/engine.py', module_content)
    print("✓ Created src/ranking/engine.py")

def create_panels():
    """Create src/visualization/panels.py"""
    content = read_file('crypto_screener.py')
    
    multi_factor = extract_class(content, 'MultiFactorPanel', 790)
    funding_rate = extract_class(content, 'FundingRatePanel', 911)
    long_short = extract_class(content, 'LongShortRatioPanel', 1062)
    
    module_content = '''"""
Visualization Panels Module

Contains panel classes for different visualization types.
"""

import logging
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)


''' + multi_factor + '\n\n\n' + funding_rate + '\n\n\n' + long_short + '\n'
    
    write_file('src/visualization/panels.py', module_content)
    print("✓ Created src/visualization/panels.py")

def create_dashboard():
    """Create src/visualization/dashboard.py"""
    content = read_file('crypto_screener.py')
    
    class_code = extract_class(content, 'DashboardBuilder', 1221)
    
    module_content = '''"""
Dashboard Builder Module

Builds complete visualization dashboard with multiple panels.
"""

import logging
import pandas as pd
import matplotlib.pyplot as plt
from .panels import MultiFactorPanel, FundingRatePanel, LongShortRatioPanel

logger = logging.getLogger(__name__)


''' + class_code + '\n'
    
    write_file('src/visualization/dashboard.py', module_content)
    print("✓ Created src/visualization/dashboard.py")

def update_init_files():
    """Update __init__.py files with proper imports"""
    
    # src/data/__init__.py
    write_file('src/data/__init__.py', '''"""Data fetching module."""

from .fetcher import MarketDataFetcher

__all__ = ['MarketDataFetcher']
''')
    
    # src/signals/__init__.py
    write_file('src/signals/__init__.py', '''"""Trading signals module."""

from .generator import SignalGenerator
from .ic_weights import ICWeightCalculator
from .scorer import MultiFactorScorer

__all__ = ['SignalGenerator', 'ICWeightCalculator', 'MultiFactorScorer']
''')
    
    # src/ranking/__init__.py
    write_file('src/ranking/__init__.py', '''"""Ranking module."""

from .engine import RankingEngine

__all__ = ['RankingEngine']
''')
    
    # src/visualization/__init__.py
    write_file('src/visualization/__init__.py', '''"""Visualization module."""

from .panels import MultiFactorPanel, FundingRatePanel, LongShortRatioPanel
from .dashboard import DashboardBuilder

__all__ = ['MultiFactorPanel', 'FundingRatePanel', 'LongShortRatioPanel', 'DashboardBuilder']
''')
    
    print("✓ Updated __init__.py files")

def main():
    """Extract all modules"""
    print("\n" + "=" * 70)
    print("EXTRACTING MODULES FROM crypto_screener.py")
    print("=" * 70 + "\n")
    
    create_data_fetcher()
    create_signal_generator()
    create_ic_weights()
    create_scorer()
    create_ranking_engine()
    create_panels()
    create_dashboard()
    update_init_files()
    
    print("\n" + "=" * 70)
    print("MODULE EXTRACTION COMPLETE!")
    print("=" * 70)
    print("\nAll modules have been created in src/")
    print("You can now run: py main.py")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
