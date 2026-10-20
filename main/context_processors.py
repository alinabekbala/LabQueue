# main/context_processors.py
"""Контекст-процессор: добавляет переменную `theme` во ВСЕ шаблоны."""
from .state import get_theme


def ui_state(request):
    return {"theme": get_theme(request)}
