# main/views.py
"""Представления (views): принимают запрос, работают с ORM, отдают шаблон."""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import state
from .forms import LabSlotForm, LoginForm, RegisterForm, SubmissionForm
from .models import LabSlot, Subject, Submission


def is_teacher(user):
    """Преподаватель = сотрудник (is_staff). Создаётся через админку."""
    return user.is_authenticated and user.is_staff


teacher_required = user_passes_test(is_teacher, login_url="login")


def _can_manage(user, submission):
    """Править/удалять запись может её автор или преподаватель."""
    return is_teacher(user) or submission.student_id == user.id


# ---------- Регистрация и вход ----------
def register_view(request):
    if request.user.is_authenticated:
        return redirect("slot_list")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Добро пожаловать, {user.username}!")
        return redirect("slot_list")
    return render(request, "main/register.html", {"form": form})


class RememberLoginView(LoginView):
    """Вход с флажком «Запомнить меня» (ЛЗ 8: срок жизни сессии).

    Без флажка cookie сессии живёт до закрытия браузера, с флажком — 30 дней.
    """
    template_name = "main/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)  # выполняет вход и готовит redirect
        if form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(state.REMEMBER_ME_AGE)
        else:
            self.request.session.set_expiry(0)  # 0 = до закрытия браузера
        return response


# ---------- Слоты ----------
def slot_list_view(request):
    """READ: список слотов с фильтром по дисциплине.

    ЛЗ 8: фильтр, список просмотренных слотов и счётчик визитов лежат в
    СЕССИИ, а время прошлого визита — в COOKIE.
    """
    session = request.session
    session[state.SESSION_VISITS] = session.get(state.SESSION_VISITS, 0) + 1

    # Фильтр: пришёл в адресе (?subject=2) — запоминаем, не пришёл — берём из сессии.
    filter_restored = False
    if "subject" in request.GET:
        selected = request.GET["subject"]
        if selected == "" or selected.isdigit():
            session[state.SESSION_FILTER] = selected
        else:
            selected = ""
    else:
        selected = session.get(state.SESSION_FILTER, "")
        filter_restored = bool(selected)

    slots = LabSlot.objects.select_related("subject", "teacher").annotate(
        taken_count=Count("submissions")
    )
    if selected.isdigit():
        slots = slots.filter(subject_id=int(selected))

    # Недавно просмотренные слоты: в сессии хранятся только id, объекты берём из БД.
    viewed_ids = session.get(state.SESSION_VIEWED, [])
    viewed_by_id = LabSlot.objects.select_related("subject").in_bulk(viewed_ids)
    recent_slots = [viewed_by_id[i] for i in viewed_ids if i in viewed_by_id]

    response = render(request, "main/slot_list.html", {
        "slots": slots,
        "filtered": bool(selected),
        "subjects": Subject.objects.all(),
        "selected": selected,
        "filter_restored": filter_restored,
        "recent_slots": recent_slots,
        "visits": session[state.SESSION_VISITS],
        "last_visit": state.read_last_visit(request),   # из cookie ДО обновления
    })
    # Обновляем cookie «последний визит» (метка времени в секундах).
    response.set_cookie(
        state.LAST_VISIT_COOKIE, str(int(timezone.now().timestamp())),
        max_age=state.LAST_VISIT_MAX_AGE, samesite="Lax",
    )
    return response


@teacher_required
def slot_create_view(request):
    """CREATE слота (преподаватель)."""
    form = LabSlotForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Слот создан!")
        return redirect("slot_list")
    return render(request, "main/slot_form.html", {"form": form, "title": "Новый слот"})


@teacher_required
def slot_update_view(request, pk):
    """UPDATE слота (преподаватель)."""
    slot = get_object_or_404(LabSlot, pk=pk)
    form = LabSlotForm(request.POST or None, instance=slot)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Слот обновлён!")
        return redirect("slot_list")
    return render(request, "main/slot_form.html", {"form": form, "title": "Редактирование слота"})


@teacher_required
def slot_delete_view(request, pk):
    """DELETE слота (преподаватель), с подтверждением."""
    slot = get_object_or_404(LabSlot, pk=pk)
    if request.method == "POST":
        slot.delete()
        messages.success(request, "Слот удалён вместе с записями на него.")
        return redirect("slot_list")
    return render(request, "main/slot_delete.html", {"slot": slot})


# ---------- Записи на защиту ----------
@login_required
def submission_list_view(request):
    """READ: студент видит свои записи, преподаватель — все."""
    qs = Submission.objects.select_related("slot__subject", "slot__teacher")
    if not is_teacher(request.user):
        qs = qs.filter(student=request.user)
    return render(request, "main/submission_list.html", {
        "submissions": qs, "status_choices": Submission.STATUS_CHOICES,
    })


@login_required
def book_slot_view(request, slot_id):
    """CREATE: запись студента на слот.

    ЛЗ 8: открытый слот попадает в список «недавно просмотренных» (сессия),
    а ФИО и группа после первой записи подставляются в форму сами (сессия).
    """
    slot = get_object_or_404(LabSlot, pk=slot_id)
    state.remember_viewed_slot(request.session, slot.id)

    if slot.submissions.count() >= slot.max_students:
        messages.error(request, "На этот слот больше нет свободных мест!")
        return redirect("slot_list")

    initial = request.session.get(state.SESSION_PROFILE, {})
    form = SubmissionForm(request.POST or None, initial=initial, slot=slot,
                          user=request.user, is_teacher=is_teacher(request.user))
    if request.method == "POST" and form.is_valid():
        submission = form.save(commit=False)
        submission.slot = slot
        submission.student = request.user
        submission.save()
        # Запоминаем данные студента для следующей записи (передача между страницами).
        request.session[state.SESSION_PROFILE] = {
            "student_name": submission.student_name,
            "group_name": submission.group_name,
        }
        messages.success(request, f"Вы записались на защиту лабы №{submission.lab_number}!")
        return redirect("submission_list")
    return render(request, "main/book_slot.html", {
        "form": form, "slot": slot,
        "prefilled": bool(initial) and request.method != "POST",
    })


@login_required
def submission_update_view(request, pk):
    """UPDATE: редактирование записи (статус меняет только преподаватель)."""
    submission = get_object_or_404(Submission, pk=pk)
    if not _can_manage(request.user, submission):
        raise PermissionDenied
    form = SubmissionForm(request.POST or None, instance=submission,
                          user=request.user, is_teacher=is_teacher(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Запись обновлена!")
        return redirect("submission_list")
    return render(request, "main/submission_update.html",
                  {"form": form, "submission": submission})


@login_required
def submission_delete_view(request, pk):
    """DELETE: удаление записи с подтверждением."""
    submission = get_object_or_404(Submission, pk=pk)
    if not _can_manage(request.user, submission):
        raise PermissionDenied
    if request.method == "POST":
        submission.delete()
        messages.success(request, "Запись удалена.")
        return redirect("submission_list")
    return render(request, "main/submission_delete.html", {"submission": submission})


# ---------- Динамические компоненты и события (ЛЗ 9) ----------
def slot_seats_view(request, pk):
    """AJAX: JSON с числом занятых мест (страница записи обновляет его сама)."""
    slot = get_object_or_404(
        LabSlot.objects.annotate(taken_count=Count("submissions")), pk=pk
    )
    return JsonResponse({
        "taken": slot.taken,
        "max": slot.max_students,
        "free": slot.free_places,
        "is_full": slot.is_full,
    })


@require_POST
def submission_status_view(request, pk):
    """AJAX (POST, JSON): преподаватель меняет статус записи без перезагрузки.

    Права проверяются на СЕРВЕРЕ: скрыть выпадающий список в шаблоне мало.
    CSRF-токен браузер присылает в заголовке X-CSRFToken.
    """
    if not is_teacher(request.user):
        return JsonResponse({"ok": False, "error": "Недостаточно прав"}, status=403)
    submission = get_object_or_404(Submission, pk=pk)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Некорректный JSON"}, status=400)
    status = data.get("status") if isinstance(data, dict) else None
    if status not in dict(Submission.STATUS_CHOICES):
        return JsonResponse({"ok": False, "error": "Неизвестный статус"}, status=400)
    submission.status = status
    submission.save(update_fields=["status"])
    return JsonResponse({"ok": True, "status": status, "label": submission.get_status_display()})


# ---------- Состояние приложения: cookies и сессия (ЛЗ 8) ----------
def set_theme_view(request, theme):
    """Сохраняет тему оформления в COOKIE и возвращает пользователя назад."""
    if theme not in state.THEMES:
        raise Http404("Неизвестная тема")
    next_url = request.GET.get("next", "")
    # Защита от open redirect: возвращаем только на адреса нашего же сайта.
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse("slot_list")
    response = redirect(next_url)
    response.set_cookie(
        state.THEME_COOKIE, theme, max_age=state.THEME_MAX_AGE, samesite="Lax"
    )
    return response


# Пояснения для страницы состояния
SESSION_NOTES = {
    state.SESSION_FILTER: "выбранный фильтр дисциплины",
    state.SESSION_VIEWED: "id недавно просмотренных слотов",
    state.SESSION_PROFILE: "ФИО и группа для автозаполнения формы",
    state.SESSION_VISITS: "сколько раз открыта главная страница",
    "_auth_user_id": "id вошедшего пользователя (вход Django)",
    "_auth_user_backend": "способ входа (Django)",
    "_auth_user_hash": "контрольная сумма пароля (Django)",
    "_session_expiry": "срок жизни сессии в секундах («запомнить меня»)",
}
COOKIE_NOTES = {
    settings.SESSION_COOKIE_NAME: "идентификатор сессии; сами данные лежат на сервере",
    settings.CSRF_COOKIE_NAME: "защита форм от подделки запросов (CSRF)",
    state.THEME_COOKIE: "тема оформления (хранится в браузере)",
    state.LAST_VISIT_COOKIE: "время прошлого визита (хранится в браузере)",
}
# Значения этих ключей не показываем даже на странице демонстрации.
HIDDEN_SESSION_KEYS = {"_auth_user_hash"}
HIDDEN_COOKIES = {settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME}


def state_view(request):
    """Показывает, что сейчас хранится в сессии и в cookies этого браузера."""
    session = request.session
    session_rows = [
        {"name": key, "value": value, "hidden": key in HIDDEN_SESSION_KEYS,
         "note": SESSION_NOTES.get(key, "")}
        for key, value in session.items()
    ]
    cookie_rows = [
        {"name": name, "value": value, "hidden": name in HIDDEN_COOKIES,
         "note": COOKIE_NOTES.get(name, "")}
        for name, value in request.COOKIES.items()
    ]
    return render(request, "main/state.html", {
        "session_rows": session_rows,
        "cookie_rows": cookie_rows,
        "session_key": (session.session_key or "")[:8],
        "expire_at_browser_close": session.get_expire_at_browser_close(),
        "expiry_age_days": round(session.get_expiry_age() / 86400, 1),
    })


@require_POST
def state_reset_view(request):
    """Очищает данные приложения из сессии и удаляет наши cookies (вход не затрагивается)."""
    for key in state.APP_SESSION_KEYS:
        request.session.pop(key, None)
    messages.success(request, "Данные сессии и cookies приложения сброшены.")
    response = redirect("state")
    response.delete_cookie(state.LAST_VISIT_COOKIE)
    response.delete_cookie(state.THEME_COOKIE)
    return response
