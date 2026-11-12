# ЛЗ 12. Безопасность web-приложения: анализ уязвимостей и защитные механизмы Django

Задача: проанализировать учебное приложение LabQueue на типичные уязвимости (OWASP) и применить защитные механизмы фреймворка.
Главная мысль лекции: большинство защит уже встроено в Django, задача разработчика не отключать их и не обходить.

## Анализ приложения

| Угроза | Где могла быть в LabQueue | Что нашли | Защита | Где в коде |
|---|---|---|---|---|
| **XSS** (чужой скрипт) | ФИО, группа, аудитория, поисковая строка, сообщения об ошибках, JS | `{{ field.help_text\|safe }}` в форме (обход экранирования, **исправлено**), остальной вывод экранируется | автоэкранирование шаблонов, `textContent` в JS, CSP | `_form_fields.html`, `dynamic.js`, `settings.py` (`SECURE_CSP`) |
| **SQL Injection** | поиск `?q=`, сортировка `?sort=`, фильтры | сырого SQL нет, везде ORM | `filter()`, `Q(...icontains)`, белый список сортировок | `filters.py`, `views.py` |
| **CSRF** | формы записи, удаления, выхода, fetch POST | все формы с `{% csrf_token %}`, fetch шлёт `X-CSRFToken`, `csrf_exempt` нигде нет | `CsrfViewMiddleware`, `SameSite=Lax`, изменения только POST | `base.html`, `dynamic.js` (`request()`), `settings.py` |
| **Управление доступом** | `/submission/<id>/edit/`, `/delete/`, `/status/`, страницы преподавателя | чужая запись отвечала 403: id существует (**исправлено на 404**) | `login_required`, `teacher_required`, владелец в самом запросе | `views.py` (`_own_submission_or_404`) |
| **Валидация** | запись на слот, JSON смены статуса | проверка есть и на сервере (форма), JS только подсказывает | `ModelForm`, `clean_*`, 400 на неверный JSON | `forms.py`, `views.py` |
| **Misconfiguration** | `settings.py` | ключ с запасным значением, `DEBUG` включён по умолчанию, нет настроек HTTPS | ключ и хосты из окружения, в боевом режиме обязательны HTTPS, HSTS, Secure cookie | `settings.py` |
| **Open redirect** | `?next=` при смене темы | уже проверялся | `url_has_allowed_host_and_scheme` | `views.py` (`set_theme_view`) |

## Что изменено в ЛЗ 12
1. **Убран `|safe`** у `help_text` в `_form_fields.html`: пользовательский или чужой текст больше нигде не выводится как разметка.
2. **Проверка владельца в запросе.** `_own_submission_or_404(user, pk)`: студент ищет запись только среди своих, преподаватель среди всех.
   Чужая запись даёт **404**, как будто её нет (`/submission/42/` → `/submission/43/` ничего не раскрывает). Раньше было 403.
   Для JSON-удаления ответ `{"ok": false, "error": "Запись не найдена"}` со статусом 404.
3. **Content-Security-Policy** (встроенный в Django 6 `ContentSecurityPolicyMiddleware`, настройка `SECURE_CSP`): скрипты только со своего сайта и `cdn.jsdelivr.net`,
   `fetch` только на свой адрес, запрещены `object`, чужие формы и встраивание в чужие страницы. Встроенного JavaScript в шаблонах нет.
4. **Настройки безопасности** в `settings.py`: `CSRF_COOKIE_HTTPONLY`, `CSRF_COOKIE_SAMESITE`, `X_FRAME_OPTIONS = 'DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF`.
   При `DJANGO_DEBUG=0` включаются `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, HSTS, и без `DJANGO_SECRET_KEY` проект не запускается.
   `python manage.py check --deploy` показывает 0 замечаний.
5. **ЛЗ 11 по лекции**: над списком во время загрузки появляется надпись «Загрузка…» (кнопки при запросе блокируются и раньше).

## Что уже было защищено (из ЛЗ 6–11)
- Права до поиска и фильтров: студент видит в «Моих записях» только свои строки.
- Сессионная cookie: `HttpOnly`, `SameSite=Lax`; выход только POST-запросом.
- Статус записи может менять только преподаватель, даже прямым запросом (JSON 403, поле `status` у студента удалено из формы).
- Проверка ссылки: только `github.com` и `gitlab.com`, схема `javascript:` не проходит.

## Файлы
| Файл | Что изменилось |
|---|---|
| `main/templates/main/_form_fields.html` | убран `\|safe` |
| `main/views.py` | `_own_submission_or_404`, 404 вместо 403 в правке и удалении, удалён `_can_manage` |
| `mysite/settings.py` | `SECURE_CSP`, CSP middleware, cookie, HTTPS-режим, ключ и хосты из окружения |
| `main/static/main/css/style.css` | надпись «Загрузка…» |
| `main/test_security.py` | 30 тестов-атак (всего в проекте 158) |
| `main/tests.py`, `main/test_ajax_lists.py` | ожидание 404 вместо 403 для чужой записи |

## Как показать
1. Студент: «Запись на слот», в ФИО введите `<script>alert('XSS')</script> Иванов`. В «Моих записях» текст виден как текст, окно alert не появилось. Показать «Просмотр кода» (`&lt;script&gt;`).
2. Поиск `' OR '1'='1` на главной: «Ничего не найдено», а не все слоты.
3. Адрес `/submission/<id чужой записи>/edit/`: **404**. Для сравнения несуществующий id даёт тот же ответ.
4. DevTools → Console, на странице `fetch('/submission/1/delete/', {method:'POST'})`: **403** (нет токена). В Network у обычного удаления в Headers виден `X-CSRFToken`.
5. DevTools → Network → Headers ответа страницы: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options`. В Console вставка `document.body.append(Object.assign(document.createElement('script'),{textContent:'1'}))` даёт ошибку «Refused to execute inline script».
6. DevTools → Application → Cookies: у `sessionid` и `csrftoken` стоят `HttpOnly` и `SameSite=Lax`.
7. Терминал: `python manage.py check --deploy` (с переменными окружения, см. выше) и `python manage.py test main.test_security`.
