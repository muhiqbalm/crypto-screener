"""Default sizing must be bit-identical to the production engine (a259ceb).

    LAB_ENGINE_PATH=/root/bmtm-lab-engine python bitident.py > a.txt
    LAB_ENGINE_PATH=/tmp/sizing/engine    python bitident.py > b.txt ; cmp a.txt b.txt
Full range START..END, the four presets' production params, Lab costs.
"""
import hashlib

from common import *  # noqa: F401,F403

for name, (sym, p) in presets().items():
    df, _ = frame(sym)
    res = run(df, p)
    h = hashlib.sha256()
    for t in res.trades:
        h.update(repr((str(t.entry_timestamp), t.entry_price, t.quantity, str(t.exit_timestamp), t.exit_price,
                       t.exit_reason, t.net_pnl, t.fees, t.funding)).encode())
    for ts, e in res.equity_curve:
        h.update(repr((str(ts), e)).encode())
    m = ea.metrics(res)
    print(name, len(res.trades), repr(m["net_return_pct"]), repr(m["max_dd_pct"]), h.hexdigest())
