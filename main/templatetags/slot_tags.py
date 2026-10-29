# main/templatetags/slot_tags.py
"""Свои теги и фильтры шаблонов (ЛЗ 9).

* ``ru_places``   — фильтр: правильное склонение «1 место / 2 места / 5 мест».
* ``top_free_slots`` — inclusion_tag: компонент «Больше всего свободных мест»,
  сам запрашивает данные, поэтому view страницы про него ничего не знает.
* ``nav_badge``   — inclusion_tag: счётчик в меню, зависит от роли пользователя.
"""
from django import template
from django.db.models import Count, F

from main.models import LabSlot, Submission

register = template.Library()


@register.filter
def ru_places(value):
    """5 -> «5 мест», 1 -> «1 место», 3 -> «3 места»."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    if 11 <= n % 100 <= 14:
        word = "мест"
    elif n % 10 == 1:
        word = "место"
    elif 2 <= n % 10 <= 4:
        word = "места"
    else:
        word = "мест"
    return f"{n} {word}"


@register.inclusion_tag("main/_top_free.html")
def top_free_slots(limit=3):
    """Компонент: слоты с наибольшим числом свободных мест (один запрос к БД)."""
    slots = (
        LabSlot.objects.select_related("subject")
        .annotate(taken_count=Count("submissions"))
        .annotate(free=F("max_students") - Count("submissions"))
        .filter(free__gt=0)
        .order_by("-free", "date_time")[:limit]
    )
    return {"slots": slots}


@register.inclusion_tag("main/_nav_badge.html", takes_context=True)
def nav_badge(context):
    """Компонент в меню: преподавателю — сколько записей ждёт проверки,
    студенту — сколько его записей ещё не защищено."""
    user = context.get("user")
    if user is None or not user.is_authenticated:
        return {"count": 0, "title": ""}
    waiting = Submission.objects.filter(status=Submission.STATUS_WAITING)
    if user.is_staff:
        return {"count": waiting.count(), "title": "Записей ждёт проверки"}
    return {"count": waiting.filter(student=user).count(), "title": "Ваших записей ждёт защиты"}
