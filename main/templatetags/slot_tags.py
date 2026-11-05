# main/templatetags/slot_tags.py
"""Свои теги и фильтры шаблонов (ЛЗ 9).

* ``ru_places``   — фильтр: правильное склонение «1 место / 2 места / 5 мест».
* ``top_free_slots`` — inclusion_tag: компонент «Больше всего свободных мест»,
  сам запрашивает данные, поэтому view страницы про него ничего не знает.
* ``nav_badge``   — inclusion_tag: счётчик в меню, зависит от роли пользователя.
"""
from django import template
from django.core.paginator import Paginator
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


# ---------- ЛЗ 10: списки, сортировка, пагинация ----------
@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Строка запроса текущей страницы с заменой параметров.

    {% url_replace page=3 %} -> «q=веб&sort=free&page=3»: поиск и фильтры сохраняются.
    """
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@register.inclusion_tag("main/_sort_th.html", takes_context=True)
def sort_th(context, field, label):
    """Заголовок колонки: клик сортирует по возрастанию, повторный клик — по убыванию."""
    query = context["request"].GET.copy()
    current = context.get("current_sort", "")
    query["sort"] = "-" + field if current == field else field
    query.pop("page", None)                       # при смене сортировки — на первую страницу
    arrow = "▲" if current == field else "▼" if current == "-" + field else ""
    return {"url": "?" + query.urlencode(), "label": label, "arrow": arrow}


@register.inclusion_tag("main/_pagination.html", takes_context=True)
def pagination(context, page_obj):
    """Постраничная навигация с сохранением поиска и фильтров."""
    request = context["request"]

    def link(number):
        query = request.GET.copy()
        query["page"] = number
        return "?" + query.urlencode()

    items = []
    for number in page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=1, on_ends=1):
        gap = number == Paginator.ELLIPSIS
        items.append({"number": number, "gap": gap,
                      "url": None if gap else link(number),
                      "current": number == page_obj.number})
    return {
        "page_obj": page_obj, "items": items,
        "prev_url": link(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "next_url": link(page_obj.next_page_number()) if page_obj.has_next() else None,
    }
