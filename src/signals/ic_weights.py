"""
IC Weight Calculator Module

Manages Information Coefficient (IC) weights for trading signals.
"""

import logging

logger = logging.getLogger(__name__)


class ICWeightCalculator:
    """
    Manages Information Coefficient (IC) weights for trading signals.
    
    IC weights represent the historical predictive power of each signal type.
    Higher IC weight indicates stronger historical correlation between the signal
    and future returns. These weights are used to combine multiple signals into
    a multi-factor score.
    
    Current Implementation:
    - Uses calibrated IC weights for 5 signal factors
    - Real implementation would calculate IC weights from historical backtesting
    - IC weights would be updated periodically based on rolling performance analysis
    """
    
    def __init__(self):
        """
        Initialize with calibrated IC weights for all signal factors.
        
        IC Weights (sum to 1.0):
        - momentum_30d: 0.30 (trend-following, strongest alpha in crypto)
        - reversal_1d: 0.10 (mean-reversion, lower weight due to noise)
        - funding_rate: 0.25 (contrarian derivatives signal, high predictive value)
        - sentiment_ls: 0.15 (contrarian crowd positioning)
        - oi_momentum: 0.20 (OI-price matrix, structural flow signal)
        
        Rationale for weights:
        - Momentum and funding rate carry the most predictive power
        - OI momentum captures structural market flow (new positions vs liquidations)
        - Sentiment provides crowd-contrarian alpha
        - Reversal is lowest-weighted due to high noise in 1-day timeframe
        - Weights sum to 1.0 for interpretability (though not strictly required)
        
        Real Implementation Note:
        - Production version would calculate IC weights from historical data
        - Would use rolling window analysis (e.g., past 12 months)
        - Would adjust weights based on market regime (trending vs. mean-reverting)
        - Would include confidence intervals and statistical significance tests
        """
        self.weights = {
            'momentum_30d': 0.30,
            'reversal_1d': 0.10,
            'funding_rate': 0.25,
            'sentiment_ls': 0.15,
            'oi_momentum': 0.20,
        }
        
        logger.info(f"ICWeightCalculator initialized with weights: {self.weights}")
    
    def get_weight(self, signal_name: str) -> float:
        """
        Return IC weight for a specific signal.
        
        Args:
            signal_name: Name of the signal (e.g., 'reversal_1d', 'momentum_30d',
                         'funding_rate', 'sentiment_ls', 'oi_momentum')
            
        Returns:
            float: IC weight for the signal (0.0 to 1.0 typically)
            
        Raises:
            KeyError: If signal_name is not found in weights dictionary
        """
        if signal_name not in self.weights:
            error_msg = f"Signal '{signal_name}' not found in IC weights. Available signals: {list(self.weights.keys())}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        weight = self.weights[signal_name]
        logger.debug(f"Retrieved IC weight for '{signal_name}': {weight}")
        
        return weight
