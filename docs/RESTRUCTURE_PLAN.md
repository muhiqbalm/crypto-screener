# Project Restructuring Plan

## New Structure

```
crypto-screener/
├── src/
│   ├── __init__.py
│   ├── exchange/
│   │   ├── __init__.py
│   │   └── connector.py          # ExchangeConnector class
│   ├── data/
│   │   ├── __init__.py
│   │   └── fetcher.py             # MarketDataFetcher class
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── generator.py           # SignalGenerator class
│   │   ├── ic_weights.py          # ICWeightCalculator class
│   │   └── scorer.py              # MultiFactorScorer class
│   ├── ranking/
│   │   ├── __init__.py
│   │   └── engine.py              # RankingEngine class
│   ├── visualization/
│   │   ├── __init__.py
│   │   ├── panels.py              # MultiFactorPanel, FundingRatePanel, LongShortRatioPanel
│   │   └── dashboard.py           # DashboardBuilder class
│   └── utils/
│       ├── __init__.py
│       └── logger.py              # Logging configuration
├── tests/
│   ├── __init__.py
│   ├── test_exchange/
│   ├── test_data/
│   ├── test_signals/
│   ├── test_ranking/
│   └── test_visualization/
├── demos/
│   ├── demo_exchange_connector.py
│   ├── demo_fetch_all_data.py
│   └── ...
├── docs/
│   ├── ERROR_HANDLING_SUMMARY.md
│   ├── TASK_*.md
│   └── ...
├── output/
│   ├── logs/
│   └── dashboards/
├── main.py                        # Entry point
├── requirements.txt
├── .gitignore
└── README.md
```

## Benefits

1. **Modular**: Each component in its own module
2. **Testable**: Tests organized by module
3. **Maintainable**: Easy to find and update code
4. **Scalable**: Easy to add new features
5. **Clean**: Separate concerns (data, signals, visualization)
