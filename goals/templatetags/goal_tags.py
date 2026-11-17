from django import template

register = template.Library()


@register.filter
def pct(v):
    if v in (None, ""):
        return "—"
    v = float(v)
    return f"{v:.0f}%" if v == int(v) else f"{v:.1f}%"


@register.filter
def bullets(text):
    """Split KPI text on newlines / '>' markers into list items."""
    if not text:
        return []
    parts = [p.strip().lstrip(">").strip() for p in text.replace("\r", "").split("\n")]
    return [p for p in parts if p]


@register.filter
def get(d, k):
    return d.get(k, 0)
