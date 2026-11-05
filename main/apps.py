import re

from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _unicode_like(pattern, value, escape=None):
    """LIKE без учёта регистра для любых букв (в SQLite он работает только для латиницы).

    Нужен для поиска на русском: «иманбек» должен находить «Иманбек».
    """
    if pattern is None or value is None:
        return None
    parts, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if escape and ch == escape and i + 1 < len(pattern):
            i += 1
            parts.append(re.escape(pattern[i]))
        elif ch == "%":
            parts.append(".*")
        elif ch == "_":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
        i += 1
    return int(bool(re.fullmatch("".join(parts), str(value), re.IGNORECASE | re.DOTALL)))


def _install_unicode_like(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        raw = connection.connection
        raw.create_function("like", 2, _unicode_like)
        raw.create_function("like", 3, _unicode_like)


class MainConfig(AppConfig):
    name = 'main'

    def ready(self):
        connection_created.connect(_install_unicode_like)
