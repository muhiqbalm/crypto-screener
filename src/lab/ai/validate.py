"""Output check: the model may only repeat facts, never invent them.

  * every number in the sentence and in each factor value must appear in the facts sent
    (same value; sign, "$", "%" and thousands separators ignored, no rounding allowed);
  * a factor must be one the facts actually contain (missing data is never summarised);
  * our own rule (``efek_sistem``) wins over the model's effect;
  * the sentence with an invented number rejects the whole summary (nothing is shown);
    a factor with one is dropped. Everything found is kept in ``validation`` for the admin.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from .facts import EFFECTS, FACTOR_KEYS, LABELS, SOURCES, Facts

MAX_SENTENCE = 400
MAX_VALUE = 160
MAX_FACTORS = 6

# A number not glued to a word: "72,930", "0.0042", "−0.6", "$74", "1,5" (decimal comma), "4" in "4H".
_NUM = re.compile(r"(?<![A-Za-z0-9_.,])[+\-−]?\$?(\d+(?:[.,]\d+)*)")


def _parse(token: str) -> Optional[Decimal]:
    t = token
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):      # exchange style 1,234.56
        t = t.replace(",", "")
    elif re.fullmatch(r"\d+,\d{1,2}", t):                       # decimal comma 1,5 / 0,25
        t = t.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):              # dotted thousands 2.832.000
        t = t.replace(".", "")
    else:
        t = t.replace(",", "")
    if t.count(".") > 1:
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list[tuple[str, Optional[Decimal]]]:
    return [(m.group(0), _parse(m.group(1))) for m in _NUM.finditer(text or "")]


def _walk(x: Any) -> Iterable[str]:
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _walk(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _walk(v)
    elif isinstance(x, bool) or x is None:
        return
    else:
        yield str(x)


def allowed_numbers(facts: dict) -> set[Decimal]:
    out: set[Decimal] = set()
    for s in _walk(facts):
        for _, v in numbers_in(s.replace("_", " ")):
            if v is not None:
                out.add(abs(v))
    return out


def ungrounded(text: str, allowed: set[Decimal]) -> list[str]:
    bad = []
    for tok, v in numbers_in(text):
        if v is None or abs(v) not in allowed:
            bad.append(tok)
    return bad


def check(raw: Any, f: Facts) -> tuple[str, Optional[dict], dict]:
    """(status ok | rejected, output to show or None, validation report)."""
    rep: dict[str, Any] = {"sentence_ungrounded": [], "dropped_factors": [], "effects_overridden": []}
    if not isinstance(raw, dict):
        rep["reason"] = "output bukan objek JSON"
        return "rejected", None, rep
    sentence = " ".join(str(raw.get("sentence") or "").split())
    if not sentence:
        rep["reason"] = "kalimat kosong"
        return "rejected", None, rep
    if len(sentence) > MAX_SENTENCE:
        rep["reason"] = f"kalimat terlalu panjang ({len(sentence)} karakter)"
        return "rejected", None, rep
    allowed = allowed_numbers(f.facts)
    bad = ungrounded(sentence, allowed)
    if bad:
        rep["sentence_ungrounded"] = bad
        rep["reason"] = "kalimat memuat angka yang tidak ada di data: " + ", ".join(bad)
        return "rejected", None, rep
    factors, seen = [], set()
    for item in raw.get("factors") or []:
        if not isinstance(item, dict):
            continue
        key, value, eff = item.get("factor"), " ".join(str(item.get("value") or "").split()), item.get("effect")
        why = None
        if key not in FACTOR_KEYS:
            why = "faktor tidak dikenal"
        elif key in seen:
            why = "faktor ganda"
        elif key not in f.available:
            why = "faktor tidak ada di data (data kosong)"
        elif not value or len(value) > MAX_VALUE:
            why = "nilai kosong atau terlalu panjang"
        elif eff not in EFFECTS:
            why = "efek tidak dikenal"
        else:
            nb = ungrounded(value, allowed)
            if nb:
                why = "angka tidak ada di data: " + ", ".join(nb)
        if why:
            rep["dropped_factors"].append({"factor": key, "value": value[:MAX_VALUE], "reason": why})
            continue
        sys = f.system_effects.get(key)
        if sys and eff != sys:
            rep["effects_overridden"].append({"factor": key, "model": eff, "aturan": sys})
            eff = sys
        seen.add(key)
        factors.append({"factor": key, "label": LABELS[key], "value": value, "effect": eff, "source": SOURCES[key]})
    if f.available and not factors:
        rep["reason"] = "tidak ada faktor yang lolos validasi"
        return "rejected", None, rep
    return "ok", {"sentence": sentence, "factors": factors[:MAX_FACTORS], "data_gaps": list(f.gaps)}, rep
