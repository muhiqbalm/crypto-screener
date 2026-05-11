"""
Unit tests for ICWeightCalculator class.

Tests the Information Coefficient weight management functionality including:
- Initialization with simulated weights
- Weight retrieval for valid signals
- Error handling for invalid signal names
"""

import pytest
from crypto_screener import ICWeightCalculator


def test_ic_weight_calculator_initialization():
    """Test that ICWeightCalculator initializes with correct simulated weights"""
    calculator = ICWeightCalculator()
    
    # Verify weights dictionary exists
    assert hasattr(calculator, 'weights')
    assert isinstance(calculator.weights, dict)
    
    # Verify expected weights are present
    assert 'reversal_1d' in calculator.weights
    assert 'momentum_30d' in calculator.weights
    
    # Verify weight values match specification
    assert calculator.weights['reversal_1d'] == 0.3
    assert calculator.weights['momentum_30d'] == 0.7


def test_get_weight_reversal_signal():
    """Test retrieving weight for reversal_1d signal"""
    calculator = ICWeightCalculator()
    
    weight = calculator.get_weight('reversal_1d')
    
    assert weight == 0.3
    assert isinstance(weight, float)


def test_get_weight_momentum_signal():
    """Test retrieving weight for momentum_30d signal"""
    calculator = ICWeightCalculator()
    
    weight = calculator.get_weight('momentum_30d')
    
    assert weight == 0.7
    assert isinstance(weight, float)


def test_get_weight_invalid_signal():
    """Test that get_weight raises KeyError for invalid signal name"""
    calculator = ICWeightCalculator()
    
    with pytest.raises(KeyError, match="Signal 'invalid_signal' not found"):
        calculator.get_weight('invalid_signal')


def test_get_weight_empty_string():
    """Test that get_weight raises KeyError for empty string"""
    calculator = ICWeightCalculator()
    
    with pytest.raises(KeyError):
        calculator.get_weight('')


def test_get_weight_case_sensitive():
    """Test that signal names are case-sensitive"""
    calculator = ICWeightCalculator()
    
    # Should work with correct case
    weight = calculator.get_weight('reversal_1d')
    assert weight == 0.3
    
    # Should fail with incorrect case
    with pytest.raises(KeyError):
        calculator.get_weight('Reversal_1d')
    
    with pytest.raises(KeyError):
        calculator.get_weight('REVERSAL_1D')


def test_weights_sum_to_one():
    """Test that simulated weights sum to 1.0 (for interpretability)"""
    calculator = ICWeightCalculator()
    
    total_weight = sum(calculator.weights.values())
    
    # Use approximate equality for floating point comparison
    assert abs(total_weight - 1.0) < 1e-10


def test_weights_are_positive():
    """Test that all weights are positive values"""
    calculator = ICWeightCalculator()
    
    for signal_name, weight in calculator.weights.items():
        assert weight > 0, f"Weight for {signal_name} should be positive"
        assert weight <= 1.0, f"Weight for {signal_name} should be <= 1.0"


def test_multiple_instances_independent():
    """Test that multiple ICWeightCalculator instances are independent"""
    calculator1 = ICWeightCalculator()
    calculator2 = ICWeightCalculator()
    
    # Both should have same initial weights
    assert calculator1.weights == calculator2.weights
    
    # Modifying one should not affect the other
    calculator1.weights['reversal_1d'] = 0.5
    
    assert calculator1.weights['reversal_1d'] == 0.5
    assert calculator2.weights['reversal_1d'] == 0.3


def test_get_weight_all_signals():
    """Test retrieving weights for all available signals"""
    calculator = ICWeightCalculator()
    
    # Get all signal names
    signal_names = list(calculator.weights.keys())
    
    # Should be able to retrieve weight for each signal
    for signal_name in signal_names:
        weight = calculator.get_weight(signal_name)
        assert isinstance(weight, float)
        assert weight > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
