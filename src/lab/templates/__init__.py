"""Strategy templates registry."""
from . import rosyade_family

TEMPLATES = {rosyade_family.TEMPLATE_ID: rosyade_family}


def get_template(template_id: str):
    return TEMPLATES.get(template_id)
