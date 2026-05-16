import os
import re

MAPPING = {
    'MultiFactorPanel': 'src.visualization.panels',
    'LongShortRatioPanel': 'src.visualization.panels',
    'FundingRatePanel': 'src.visualization.panels',
    'DashboardBuilder': 'src.visualization.dashboard',
    'SignalGenerator': 'src.signals.generator',
    'MultiFactorScorer': 'src.signals.scorer',
    'ICWeightCalculator': 'src.signals.ic_weights',
    'RankingEngine': 'src.ranking.engine',
    'MarketDataFetcher': 'src.data.fetcher',
    'ExchangeConnector': 'src.exchange.connector',
}

TESTS_DIR = 'tests'

for root, _, files in os.walk(TESTS_DIR):
    for file in files:
        if not file.endswith('.py'):
            continue
        
        filepath = os.path.join(root, file)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        original_content = content
        
        def replacer(match):
            # group 1 is inside parens, group 2 is without parens
            imports_str = match.group(1) if match.group(1) else match.group(2)
            imports_str = imports_str.replace('\n', '')
            imports = [i.strip() for i in imports_str.split(',')]
            
            new_imports = []
            for imp in imports:
                if not imp: continue
                module = MAPPING.get(imp, 'src')
                new_imports.append(f"from {module} import {imp}")
                
            return '\n'.join(new_imports)
            
        content = re.sub(r'from\s+crypto_screener\s+import\s+(?:\(([\s\S]*?)\)|([^\n]+))', replacer, content)
        
        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Fixed {filepath}")
