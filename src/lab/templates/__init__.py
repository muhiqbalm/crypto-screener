"""Strategy templates registry."""
from . import donchian_breakout, mean_reversion_range, rosyade_family

TEMPLATES = {m.TEMPLATE_ID: m for m in (rosyade_family, donchian_breakout, mean_reversion_range)}


def get_template(template_id: str):
    return TEMPLATES.get(template_id)
