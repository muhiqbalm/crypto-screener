"""Ringkasan AI (phase 1 of the "AI agent untuk faktor keputusan" plan): after every
``outlook_refresh`` the worker summarises, per coin, how the context factors (BTC regime,
funding, open interest, whale flow, Fear & Greed, headlines) relate to the Outlook direction.

  config.py    LAB_AI_* + ANTHROPIC_API_KEY (env first, then the screener .env); why it is off
  facts.py     the market facts sent to the model: only data our system already computed
  validate.py  every number in the output must appear in the facts; invented parts are dropped
  client.py    the one Anthropic Messages call (SDK imported lazily), structured JSON output
  store.py     lab_ai_summaries (one row per coin per 4H bar) + the daily spend
  job.py       the ``ai_factor_summary`` job (screener venv, fast lane, budget-capped)
  schedule.py  queues the job once per bar after that bar's outlook_refresh finished

Information only: the AI has no tools and no code path to any order, watch, preset or
setting. It never sees user data, e-mails or keys; it only reads market facts. Ships OFF:
it runs only with LAB_AI_ENABLED=1 and an ANTHROPIC_API_KEY in the server .env.
"""
JOB_KIND = "ai_factor_summary"
LABEL = "AI · bisa salah · bukan saran investasi"
