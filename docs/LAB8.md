# ЛЗ 8. Session и Cookies в LabQueue (Django)

## Главное отличие
| | Session | Cookie |
|---|---|---|
| Где хранится | **на сервере** (таблица `django_session`) | **в браузере** |
| Что получает браузер | только идентификатор в cookie `sessionid` | сами данные |
| Что можно хранить | любые данные приложения | только несекретное (тема, метки) |
| Доступ в Django | `request.session[...]` | `request.COOKIES[...]`, `response.set_cookie(...)` |

## Что реализовано
| Сценарий | Механизм | Где в коде |
|---|---|---|
| Запоминание фильтра дисциплины | session | `views.slot_list_view`, ключ `last_subject` |
| «Недавно просмотренные слоты» | session | `state.remember_viewed_slot`, `views.book_slot_view`, ключ `viewed_slots` |
| Автозаполнение ФИО и группы | session | `views.book_slot_view`, ключ `profile` |
| Счётчик открытий главной | session | `views.slot_list_view`, ключ `visits` |
| Тема оформления светлая/тёмная | cookie `theme` (1 год) | `views.set_theme_view`, `context_processors.ui_state`, `base.html` |
| «Прошлый визит» | cookie `last_visit` (30 дней) | `views.slot_list_view`, `state.read_last_visit` |
| «Запомнить меня» при входе | срок жизни сессии | `views.RememberLoginView`, `forms.LoginForm.remember_me` |
| Просмотр и сброс состояния | страница `/state/` | `views.state_view`, `views.state_reset_view`, `state.html` |

Настройки: `SESSION_ENGINE`, `SESSION_COOKIE_AGE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE` в `mysite/settings.py`.
Имена ключей и cookies собраны в одном модуле `main/state.py`.

## Безопасность
- Значение cookie `theme` приходит из браузера, ему не доверяем: проверка по белому списку (`state.get_theme`).
- Параметр `next` в смене темы проверяется `url_has_allowed_host_and_scheme` (защита от open redirect).
- `sessionid` и `csrftoken` не выводятся на странице состояния; `sessionid` с флагом `HttpOnly`.
- В cookie не храним ничего секретного: данные пользователя лежат в сессии на сервере.
- Сброс (`/state/reset/`) только через POST с CSRF-токеном.

## Как показать на защите
1. Войти без «запомнить меня» и показать в DevTools (F12 → Application → Cookies) `sessionid` без срока (Session).
2. Выбрать дисциплину, перейти на другую страницу и вернуться: фильтр помнится (сессия).
3. Открыть пару слотов: блок «Вы недавно смотрели».
4. Записаться и открыть форму снова: ФИО и группа подставлены.
5. Переключить тему: в Cookies появилась `theme`; обновить страницу: тема сохранилась.
6. Открыть `/state/`: показать сессию и cookies, нажать сброс.
7. В PyCharm открыть таблицу `django_session`: показать, что данные сессии лежат в БД.

## Возможные вопросы
- **Чем сессия отличается от cookie?** Сессия на сервере, в браузере только `sessionid`; cookie целиком в браузере.
- **Почему пароль/роль нельзя хранить в cookie?** Пользователь может изменить cookie. Секреты и права держим на сервере.
- **Что делает `HttpOnly`?** Скрывает cookie от JavaScript (защита от кражи через XSS).
- **Что делает `SameSite=Lax`?** Cookie не уходит со сторонних сайтов (защита от CSRF).
- **Зачем `session[...] = новый_список`?** Django сохраняет сессию, только если заметил присваивание; изменение списка «на месте» может остаться незамеченным.
- **Как работает «запомнить меня»?** `session.set_expiry(30 дней)`; без флажка `set_expiry(0)`: сессия до закрытия браузера.
