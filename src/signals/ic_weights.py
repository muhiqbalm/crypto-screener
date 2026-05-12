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
    - Uses simulated IC weights for MVP demonstration
    - Real implementation would calculate IC weights from historical backtesting
    - IC weights would be updated periodically based on rolling performance analysis
    """
    
    def __init__(self):
        """
        Initialize with simulated IC weights.
        
        Simulated IC Weights:
        - reversal_1d: 0.3 (30% weight for 1-day reversal signal)
        - momentum_30d: 0.7 (70% weight for 30-day momentum signal)
        
        Rationale for weights:
        - Momentum signals typically have stronger predictive power in trending markets
        - Reversal signals provide diversification and capture mean-reversion opportunities
        - Weights sum to 1.0 for interpretability (though not strictly required)
        
        Real Implementation Note:
        - Production version would calculate IC weights from historical data
        - Would use rolling window analysis (e.g., past 12 months)
        - Would adjust weights based on market regime (trending vs. mean-reverting)
        - Would include confidence intervals and statistical significance tests
        """
        self.weights = {
            'reversal_1d': 0.3,
            'momentum_30d': 0.7
        }
        
        logger.info(f"ICWeightCalculator initialized with weights: {self.weights}")
        logger.warning("IC weights are SIMULATED - implement historical IC calculation for production")
    
    def get_weight(self, signal_name: str) -> float:
        """
        Return IC weight for a specific signal.
        
        Args:
            signal_name: Name of the signal (e.g., 'reversal_1d', 'momentum_30d')
            
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
