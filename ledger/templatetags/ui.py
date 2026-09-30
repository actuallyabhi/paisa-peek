import re

from django import template
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(needs_autoescape=True)
def highlight(text, query, autoescape=True):
    """Wrap case-insensitive matches of `query` in <mark>. Text is escaped first, so user data stays inert."""
    text = conditional_escape(text or "")
    if not query:
        return text
    pattern = re.compile(re.escape(str(conditional_escape(query))), re.IGNORECASE)
    return mark_safe(pattern.sub(lambda m: f'<mark class="rounded bg-gold-soft px-0.5 text-ink">{m.group(0)}</mark>', text))
