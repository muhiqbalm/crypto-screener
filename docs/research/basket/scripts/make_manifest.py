#!/usr/bin/env python3
"""Build ops/lab_baskets_seed.json from the locked pre-registration + the frozen reference numbers.

    python3 docs/research/basket/scripts/make_manifest.py   (stdlib only, run from the repo root)

Every pre-registered field is copied verbatim (the seed script refuses any difference);
``expect`` comes from expectation.py; titles and notes are the only free text.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PREREG = ROOT / "docs/research/basket/prereg-basket-2026-11-12.json"
EXPECT = ROOT / "docs/research/basket/expectation.json"
OUT = ROOT / "ops/lab_baskets_seed.json"
KEYS = ("name", "label", "template_id", "timeframe", "params", "costs", "symbols", "sizing", "account")
TITLES = {"4H-BASKET-DonchianDef": "Basket Donchian 4 jam", "4H-BASKET-RosyadeVT60": "Basket Rosyade 4 jam VT60"}
NOTES = {
    "4H-BASKET-DonchianDef": (
        "Basket praregistrasi 2026-11-12 (docs/riset-2026-11-12/08-praregistrasi-basket.md, commit 52dccca). "
        "Donchian breakout 4 jam dengan parameter DEFAULT template, tanpa diubah, di 29 pair screener. "
        "Satu akun paper 10,000 USDT; tiap transaksi berisiko 0,25% saldo di stop awal strategi; cap notional "
        "total 1,5x; rem darurat -15% dari puncak. Hanya sinyal baru setelah mulai. Evaluasi otomatis di "
        "checkpoint (>= 30 transaksi, >= 28 hari, >= 8 koin, >= 10 hari entry). Paper saja."),
    "4H-BASKET-RosyadeVT60": (
        "Basket praregistrasi 2026-11-12 (docs/riset-2026-11-12/08-praregistrasi-basket.md, commit 52dccca). "
        "Rosyade Basic (setting live ETH 4H) dengan ukuran VT60, di 28 pair screener selain ETH. Satu akun "
        "paper 10,000 USDT dibagi rata 28; notional per koin = modal per koin x kelipatan VT60 engine; cap "
        "notional total 2x; rem darurat -15% dari puncak. Hanya sinyal baru setelah mulai. Evaluasi otomatis "
        "di checkpoint (>= 30 transaksi, >= 28 hari, >= 8 koin, >= 10 hari entry). Paper saja."),
}


def main() -> int:
    prereg = json.loads(PREREG.read_text())
    expect = json.loads(EXPECT.read_text())
    baskets = []
    for b in prereg["baskets"]:
        e = dict(expect["baskets"][b["name"]])
        e.update(engine_commit=expect["engine_commit"], computed_at=expect["computed_at"],
                 procedure_commit=expect["procedure_commit"])
        baskets.append({**{k: b[k] for k in KEYS}, "title": TITLES[b["name"]], "notes": NOTES[b["name"]],
                        "expect": e})
    out = {"version": 1, "generated_by": "docs/research/basket/scripts/make_manifest.py",
           "prereg": {"id": prereg["id"], "doc": prereg["doc"], "json": "docs/research/basket/prereg-basket-2026-11-12.json",
                      "commit": "52dccca"},
           "baskets": baskets}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {[b['name'] for b in baskets]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
