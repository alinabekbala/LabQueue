# main/views.py
"""Представления (views): принимают запрос, работают с ORM, отдают шаблон."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from .forms import LabSlotForm, RegisterForm, SubmissionForm
from .models import LabSlot, Subject, Submission


def is_teacher(user):
    """Преподаватель = сотрудник (is_staff). Создаётся через админку."""
    return user.is_authenticated and user.is_staff


teacher_required = user_passes_test(is_teacher, login_url="login")


def _can_manage(user, submission):
    """Править/удалять запись может её автор или преподаватель."""
    return is_teacher(user) or submission.student_id == user.id


# ---------- Регистрация ----------
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


# ---------- Слоты ----------
def slot_list_view(request):
    """READ: список слотов с фильтром по дисциплине."""
    slots = LabSlot.objects.select_related("subject", "teacher").annotate(
        taken_count=Count("submissions")
    )
    subjects = Subject.objects.all()
    selected = request.GET.get("subject", "")
    if selected.isdigit():
        slots = slots.filter(subject_id=int(selected))
    return render(request, "main/slot_list.html", {
        "slots": slots, "subjects": subjects, "selected": selected,
    })


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
    return render(request, "main/submission_list.html", {"submissions": qs})


@login_required
def book_slot_view(request, slot_id):
    """CREATE: запись студента на слот."""
    slot = get_object_or_404(LabSlot, pk=slot_id)
    if slot.submissions.count() >= slot.max_students:
        messages.error(request, "На этот слот больше нет свободных мест!")
        return redirect("slot_list")

    form = SubmissionForm(request.POST or None, slot=slot, user=request.user,
                          is_teacher=is_teacher(request.user))
    if request.method == "POST" and form.is_valid():
        submission = form.save(commit=False)
        submission.slot = slot
        submission.student = request.user
        submission.save()
        messages.success(request, f"Вы записались на защиту лабы №{submission.lab_number}!")
        return redirect("submission_list")
    return render(request, "main/book_slot.html", {"form": form, "slot": slot})


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
