# main/state.py
"""Состояние Web-приложения (ЛЗ 8): имена ключей сессии и cookies в одном месте.

Session — данные хранятся НА СЕРВЕРЕ (таблица django_session), браузеру отдаётся
только идентификатор в cookie `sessionid`.
Cookie — данные хранятся В БРАУЗЕРЕ и приходят на сервер с каждым запросом.
"""
from datetime import datetime

from django.utils import timezone

# ---------- Cookies ----------
THEME_COOKIE = "theme"
THEMES = ("light", "dark")
DEFAULT_THEME = "light"
THEME_MAX_AGE = 60 * 60 * 24 * 365          # тема помнится 1 год

LAST_VISIT_COOKIE = "last_visit"
LAST_VISIT_MAX_AGE = 60 * 60 * 24 * 30      # время визита помнится 30 дней

# ---------- Ключи сессии ----------
SESSION_FILTER = "last_subject"             # выбранный фильтр дисциплины
SESSION_VIEWED = "viewed_slots"             # недавно просмотренные слоты
SESSION_PROFILE = "profile"                 # ФИО и группа для автозаполнения формы
SESSION_VISITS = "visits"                   # счётчик посещений главной страницы
APP_SESSION_KEYS = (SESSION_FILTER, SESSION_VIEWED, SESSION_PROFILE, SESSION_VISITS)

VIEWED_LIMIT = 5                            # сколько слотов помнить
REMEMBER_ME_AGE = 60 * 60 * 24 * 30         # «Запомнить меня» = 30 дней


def get_theme(request):
    """Тема из cookie. Значению из браузера доверять нельзя — проверяем по белому списку."""
    theme = request.COOKIES.get(THEME_COOKIE, DEFAULT_THEME)
    return theme if theme in THEMES else DEFAULT_THEME


def remember_viewed_slot(session, slot_id):
    """Ставит слот в начало списка просмотренных (без дублей, не больше VIEWED_LIMIT)."""
    viewed = [i for i in session.get(SESSION_VIEWED, []) if i != slot_id]
    viewed.insert(0, slot_id)
    # Присваиваем новый список: так Django замечает изменение и сохраняет сессию.
    session[SESSION_VIEWED] = viewed[:VIEWED_LIMIT]


def read_last_visit(request):
    """Время прошлого визита из cookie (datetime) или None."""
    raw = request.COOKIES.get(LAST_VISIT_COOKIE, "")
    if not raw.isdigit():
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.get_current_timezone())
    except (OverflowError, OSError, ValueError):
        return None
