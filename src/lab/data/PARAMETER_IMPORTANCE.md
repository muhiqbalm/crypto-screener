# `parameter_importance.json`: format read by `src/lab/importance.py`

This is a snapshot of `docs/riset-2026-11-12/parameter_importance.json`, produced by the
parameter research (branch `research/param-search-2026-11`). To update it, replace the file. The API
re-reads it when its size or modification time changes, so no restart is needed.

`GET /api/v1/lab/templates/{template_id}/importance?timeframe=4h` uses this file first. If the file
has no entry for that template × timeframe, it falls back to the sensitivity of at least 5 finished
runs, and then to the template's `tunable` order. Importance is advice only: it never changes a
parameter value, a preset, a run, a watch, the holdout lock or the cost model.

## Accepted shapes

The loader is tolerant. A missing or invalid file is ignored. An entry or param that cannot be
read is skipped. Unknown fields are ignored. Labels other than the three below become `null`.

### Nested (what the research produces)

```jsonc
{
  "version": "2026-11-12",            // optional
  "date": "2026-11-12",               // shown in the UI as "riset 12 Nov 2026"
  "status": "4h+1d complete …",       // optional, passed through
  "basis": "… (daily, 2023-01-01..2026-11-09, …) …",
                                      // optional; a "YYYY-MM-DD..YYYY-MM-DD" window is
                                      // extracted and cited in the UI
  "templates": [
    {
      "template_id": "donchian_breakout",   // or "template"
      "tf": "4h",                           // or "timeframe"
      "n_trials": 4608,                     // optional
      "coins": ["BTCUSDT", "…"],            // optional (or "n_coins": 24)
      "params": [
        {
          "param": "dc_atr_mult",           // research name (or "key")
          "lab_keys": ["dc_atr_mult"],      // Lab keys; default [param].
                                            // Composites: "sides" -> ["enable_long", "enable_short"],
                                            // "notional_mult" -> ["portfolio_risk", "leverage"]
          "stability_label": "penting & stabil",
                                            // or "label"; one of: "penting & stabil",
                                            // "penting tapi tidak stabil", "tidak berpengaruh"
          "combined_share": 0.2518,         // ranking score; else "importance_mean";
                                            // else "fanova.mean"
          "fanova": {"mean": 0.19, "ci90": [0.14, 0.24]},
                                            // CI only used when fanova.mean is the score
          "coins_frac_important": 0.875,    // optional
          "folds_important": [true, true, true],
                                            // optional, one per walk-forward fold year
          "current_default": 4.0,           // optional
          "recommended": {                  // optional; the plateau of the marginal curve
            "range": [4.7, 9.9],            // numeric params, or
            "values": ["long"],             // categorical params
            "default": 7.0,
            "current_inside": false
          }
        }
      ]
    }
  ]
}
```

### Flat rows (also accepted)

```jsonc
{
  "date": "2026-11-20",
  "rows": [
    {"template": "rosyade_family", "tf": "1h", "param": "long_sl_pct",
     "importance_mean": 0.031, "importance_ci": [0.02, 0.04],
     "stability_label": "penting & stabil",
     "recommended_default": 13.0, "recommended_range": [6.5, 29.5],
     "lab_keys": ["long_sl_pct"]}
  ]
}
```

## Rules applied by the API

- A param is used only if at least one of its `lab_keys` exists in the current Lab template. The
  other keys are dropped from that row.
- Params are ranked by score, highest first. Params without a score come last.
- A row is `tunable` only when every one of its Lab keys can be searched by "Cari setting terbaik".
- The response always states `source` (`research` | `runs` | `template`), `basis`
  (for example "riset 12 Nov 2026" or "dari 14 run") and `basis_detail`.
