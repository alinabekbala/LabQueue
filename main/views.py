from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import SubmissionForm
from .models import LabSlot, Submission


def slot_list_view(request):
    """Отображает список всех доступных слотов для записи (READ)"""
    slots = LabSlot.objects.select_related('subject', 'teacher').all()
    # Затягиваем все записи, чтобы вывести их списком и дать кнопки Update/Delete
    submissions = Submission.objects.select_related(
        'slot__subject', 'slot__teacher'
    ).all()
    return render(
        request,
        'main/slot_list.html',
        {'slots': slots, 'submissions': submissions},
    )


def book_slot_view(request, slot_id):
    """Обрабатывает запись студента на конкретный слот (CREATE)"""
    slot = get_object_or_404(LabSlot, pk=slot_id)

    # Проверка на заполненность слота
    if slot.submissions.count() >= slot.max_students:
        messages.error(request, 'На этот слот больше нет свободных мест!')
        return redirect('slot_list')

    if request.method == 'POST':
        form = SubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.slot = slot
            submission.save()

            messages.success(
                request,
                f'Вы успешно записались на защиту лабы №{submission.lab_number}!',
            )
            return redirect('slot_list')
    else:
        form = SubmissionForm()

    return render(request, 'main/book_slot.html', {'form': form, 'slot': slot})


def submission_update_view(request, pk):
    """Редактирование записи/статуса (UPDATE)"""
    submission = get_object_or_404(Submission, pk=pk)
    if request.method == 'POST':
        form = SubmissionForm(request.POST, instance=submission)
        if form.is_valid():
            form.save()
            messages.success(request, 'Запись успешно обновлена!')
            return redirect('slot_list')
    else:
        form = SubmissionForm(instance=submission)

    return render(
        request,
        'main/submission_update.html',
        {'form': form, 'submission': submission},
    )


def submission_delete_view(request, pk):
    """Удаление записи (DELETE)"""
    submission = get_object_or_404(Submission, pk=pk)
    if request.method == 'POST':
        submission.delete()
        messages.success(request, 'Запись успешно удалена!')
        return redirect('slot_list')

    return render(
        request, 'main/submission_delete.html', {'submission': submission}
    )