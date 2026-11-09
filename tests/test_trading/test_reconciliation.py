from src.trading.reconciliation import find_differences


def test_matching_positions_have_no_differences():
    assert find_differences({"ETH/USDT:USDT"}, {"ETH/USDT:USDT"}) == []


def test_both_directions_are_reported():
    assert find_differences({"ETH/USDT:USDT"}, {"BTC/USDT:USDT"}) == [
        "BTC/USDT:USDT open in audit, not on exchange",
        "ETH/USDT:USDT open on exchange, not in audit",
    ]
