#!/usr/bin/env python3
"""
Demo script for ICWeightCalculator class.

This script demonstrates the usage of the ICWeightCalculator class,
showing how to initialize it and retrieve IC weights for different signals.
"""

from crypto_screener import ICWeightCalculator


def main():
    print("=" * 60)
    print("ICWeightCalculator Demo")
    print("=" * 60)
    print()
    
    # Initialize the calculator
    print("1. Initializing ICWeightCalculator...")
    calculator = ICWeightCalculator()
    print(f"   ✓ Initialized with weights: {calculator.weights}")
    print()
    
    # Retrieve weight for reversal signal
    print("2. Retrieving weight for 'reversal_1d' signal...")
    reversal_weight = calculator.get_weight('reversal_1d')
    print(f"   ✓ Reversal signal weight: {reversal_weight}")
    print()
    
    # Retrieve weight for momentum signal
    print("3. Retrieving weight for 'momentum_30d' signal...")
    momentum_weight = calculator.get_weight('momentum_30d')
    print(f"   ✓ Momentum signal weight: {momentum_weight}")
    print()
    
    # Show weight interpretation
    print("4. Weight Interpretation:")
    print(f"   - Reversal signal contributes {reversal_weight * 100}% to multi-factor score")
    print(f"   - Momentum signal contributes {momentum_weight * 100}% to multi-factor score")
    print(f"   - Total weight: {reversal_weight + momentum_weight} (normalized)")
    print()
    
    # Demonstrate error handling
    print("5. Error Handling Demo:")
    try:
        invalid_weight = calculator.get_weight('invalid_signal')
    except KeyError as e:
        print(f"   ✓ Correctly raised KeyError for invalid signal: {e}")
    print()
    
    # Show all available signals
    print("6. Available Signals:")
    for signal_name, weight in calculator.weights.items():
        print(f"   - {signal_name}: {weight}")
    print()
    
    print("=" * 60)
    print("Demo Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
