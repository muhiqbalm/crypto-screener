"""
Unit tests for MultiFactorScorer.calculate_score and classify_tiers.

Current model (see ICWeightCalculator):
    score = 0.10*reversal + 0.30*momentum + 0.25*funding + 0.15*sentiment + 0.20*oi_momentum
Tiers: A >= 67th percentile, B >= 33rd percentile, C otherwise
(1 asset -> A; 2 assets -> A/C).
"""

import numpy as np
import pandas as pd
import pytest

from src.signals.ic_weights import ICWeightCalculator
from src.signals.scorer import MultiFactorScorer

SIGNALS = [
    'reversal_signal', 'momentum_signal', 'funding_rate_signal',
    'sentiment_signal', 'oi_momentum_signal',
]
WEIGHTS = {
    'reversal_signal': 0.10,
    'momentum_signal': 0.30,
    'funding_rate_signal': 0.25,
    'sentiment_signal': 0.15,
    'oi_momentum_signal': 0.20,
}


def _expected(row: dict) -> float:
    return sum(WEIGHTS[k] * row[k] for k in SIGNALS)


class TestMultiFactorScorer:
    """Test suite for MultiFactorScorer class."""

    @pytest.fixture
    def ic_calculator(self):
        return ICWeightCalculator()

    @pytest.fixture
    def scorer(self, ic_calculator):
        return MultiFactorScorer(ic_calculator)

    def test_initialization(self, ic_calculator):
        scorer = MultiFactorScorer(ic_calculator)
        assert scorer.ic_calculator is ic_calculator

    def test_calculate_score_basic(self, scorer):
        rows = [
            dict(reversal_signal=1.0, momentum_signal=0.5, funding_rate_signal=0.2,
                 sentiment_signal=-0.4, oi_momentum_signal=1.0),
            dict(reversal_signal=0.0, momentum_signal=0.0, funding_rate_signal=0.0,
                 sentiment_signal=0.0, oi_momentum_signal=0.0),
            dict(reversal_signal=-1.0, momentum_signal=-0.5, funding_rate_signal=-0.2,
                 sentiment_signal=0.4, oi_momentum_signal=-1.0),
        ]
        df = pd.DataFrame(rows)
        df.insert(0, 'symbol', ['BTC', 'ETH', 'SOL'])

        scores = scorer.calculate_score(df)

        assert len(scores) == 3
        np.testing.assert_array_almost_equal(
            scores.values, [_expected(r) for r in rows], decimal=10
        )

    def test_calculate_score_weights(self, scorer):
        """Each signal contributes exactly its IC weight; all-ones sums to 1.0."""
        for name in SIGNALS:
            row = {k: (1.0 if k == name else 0.0) for k in SIGNALS}
            score = scorer.calculate_score(pd.DataFrame([row])).iloc[0]
            assert score == pytest.approx(WEIGHTS[name], abs=1e-12)

        ones = pd.DataFrame([{k: 1.0 for k in SIGNALS}])
        assert scorer.calculate_score(ones).iloc[0] == pytest.approx(1.0, abs=1e-12)

    def test_calculate_score_missing_columns(self, scorer):
        df = pd.DataFrame({'reversal_signal': [1.0, 0.0]})

        with pytest.raises(KeyError) as exc_info:
            scorer.calculate_score(df)

        for col in SIGNALS[1:]:
            assert col in str(exc_info.value)

    def test_calculate_score_empty_dataframe(self, scorer):
        df = pd.DataFrame({k: [] for k in SIGNALS})

        scores = scorer.calculate_score(df)

        assert len(scores) == 0
        assert scores.dtype == float

    def test_calculate_score_with_nan(self, scorer):
        """NaN in any input signal propagates to that asset's score."""
        df = pd.DataFrame({k: [1.0, 1.0, 1.0] for k in SIGNALS})
        df.loc[1, 'momentum_signal'] = np.nan
        df.loc[2, 'oi_momentum_signal'] = np.nan

        scores = scorer.calculate_score(df)

        assert scores.iloc[0] == pytest.approx(1.0)
        assert pd.isna(scores.iloc[1])
        assert pd.isna(scores.iloc[2])

    def test_classify_tiers_basic(self, scorer):
        # p33 = 3.33, p67 = 6.67
        scores = pd.Series([10.0, 8.0, 6.0, 4.0, 2.0, 0.0])

        tiers = scorer.classify_tiers(scores)

        assert list(tiers) == ['A', 'A', 'B', 'B', 'C', 'C']

    def test_classify_tiers_even_split(self, scorer):
        scores = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0, 0.0])

        tier_counts = scorer.classify_tiers(scores).value_counts()

        assert tier_counts.to_dict() == {'A': 2, 'B': 2, 'C': 2}

    def test_classify_tiers_single_asset(self, scorer):
        tiers = scorer.classify_tiers(pd.Series([5.0]))
        assert list(tiers) == ['A']

    def test_classify_tiers_two_assets(self, scorer):
        tiers = scorer.classify_tiers(pd.Series([1.0, 3.0]))
        assert list(tiers) == ['C', 'A']

    def test_classify_tiers_empty(self, scorer):
        tiers = scorer.classify_tiers(pd.Series([], dtype=float))

        assert len(tiers) == 0
        assert tiers.dtype in [object, 'object', 'str', pd.StringDtype()]

    def test_classify_tiers_all_equal(self, scorer):
        """All scores equal the 67th percentile, so all are Tier A."""
        tiers = scorer.classify_tiers(pd.Series([5.0, 5.0, 5.0, 5.0]))
        assert list(tiers) == ['A', 'A', 'A', 'A']

    def test_classify_tiers_with_ties_at_threshold(self, scorer):
        # p33 = p67 = 5.0, so every 5.0 is Tier A
        tiers = scorer.classify_tiers(pd.Series([10.0, 5.0, 5.0, 5.0, 0.0]))
        assert list(tiers) == ['A', 'A', 'A', 'A', 'C']

    def test_classify_tiers_negative_scores(self, scorer):
        # p33 = -1.33, p67 = 0.33
        tiers = scorer.classify_tiers(pd.Series([2.0, 1.0, 0.0, -1.0, -2.0, -3.0]))
        assert list(tiers) == ['A', 'A', 'B', 'B', 'C', 'C']

    def test_end_to_end_scoring_and_classification(self, scorer):
        levels = [1.5, 0.5, 0.0, -0.5, -1.5]
        df = pd.DataFrame({k: levels for k in SIGNALS})
        df.insert(0, 'symbol', ['BTC', 'ETH', 'SOL', 'AVAX', 'LINK'])

        scores = scorer.calculate_score(df)
        tiers = scorer.classify_tiers(scores)

        # All-equal signals -> score equals the signal level (weights sum to 1)
        np.testing.assert_array_almost_equal(scores.values, levels)
        assert list(tiers) == ['A', 'A', 'B', 'C', 'C']
