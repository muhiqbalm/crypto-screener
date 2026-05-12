"""Trading signals module."""

from .generator import SignalGenerator
from .ic_weights import ICWeightCalculator
from .scorer import MultiFactorScorer

__all__ = ['SignalGenerator', 'ICWeightCalculator', 'MultiFactorScorer']
