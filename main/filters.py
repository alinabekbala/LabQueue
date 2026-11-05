# main/filters.py
"""Поиск, фильтрация и сортировка списков (ЛЗ 10).

Параметры приходят в адресной строке (GET), поэтому проверяются формами Django:
неверное значение не вызывает ошибку, а просто игнорируется и показывается
сообщение. Сортировать можно только по полям из белого списка SORTS.
"""
from django import forms
from django.db.models import Count, F, Q

from .forms import BootstrapMixin
from .models import Subject, Submission, Teacher

MAX_WORDS = 5  # сколько слов запроса учитываем


def search_q(query, lookups):
    """Q-условие: каждое слово запроса должно встретиться хотя бы в одном поле."""
    condition = Q()
    for word in query.split()[:MAX_WORDS]:
        word_q = Q()
        for lookup in lookups:
            word_q |= Q(**{f"{lookup}__icontains": word})
        condition &= word_q
    return condition


class ListFilterForm(BootstrapMixin, forms.Form):
    """Общая часть: поиск q и сортировка sort по белому списку."""
    SORTS = {}          # ключ -> кортеж полей для order_by
    DEFAULT_SORT = ""
    SORT_LABELS = []    # [(ключ, подпись)] для выпадающего списка (может быть пустым)
    SEARCH_FIELDS = ()
    PLACEHOLDER = ""

    q = forms.CharField(required=False, max_length=100, label="Поиск")
    sort = forms.ChoiceField(required=False, label="Сортировка")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        keys = list(self.SORTS)
        labels = dict(self.SORT_LABELS)
        self.fields["sort"].choices = [(k, labels.get(k, k)) for k in keys]
        self._style_fields()
        self.fields["q"].widget.attrs["placeholder"] = self.PLACEHOLDER

    @property
    def current_sort(self):
        """Допустимая сортировка из запроса или сортировка по умолчанию."""
        if not self.is_bound:
            return self.DEFAULT_SORT
        self.is_valid()
        return self.cleaned_data.get("sort") or self.DEFAULT_SORT

    def cleaned(self):
        self.is_valid()
        return getattr(self, "cleaned_data", {})

    @property
    def is_filtered(self):
        """Включён ли хоть один поиск или фильтр (сортировка не считается)."""
        data = self.cleaned()
        return any(v for k, v in data.items() if k != "sort")

    def apply(self, queryset):
        data = self.cleaned()
        query = (data.get("q") or "").strip()
        if query:
            queryset = queryset.filter(search_q(query, self.SEARCH_FIELDS))
        queryset = self.apply_filters(queryset, data)
        return queryset.order_by(*self.SORTS[self.current_sort])

    def apply_filters(self, queryset, data):
        return queryset


class SlotFilterForm(ListFilterForm):
    """Фильтры списка слотов (главная страница)."""
    SORTS = {
        "date": ("date_time", "pk"),
        "-date": ("-date_time", "-pk"),
        "free": ("-free_count", "date_time", "pk"),
        "subject": ("subject__title", "date_time", "pk"),
    }
    DEFAULT_SORT = "date"
    SORT_LABELS = [
        ("date", "Дата: сначала ранние"),
        ("-date", "Дата: сначала поздние"),
        ("free", "Больше свободных мест"),
        ("subject", "Дисциплина А–Я"),
    ]
    SEARCH_FIELDS = ("subject__title", "teacher__full_name", "classroom")
    PLACEHOLDER = "Дисциплина, преподаватель, аудитория"

    subject = forms.ModelChoiceField(
        Subject.objects.all(), required=False, empty_label="Все дисциплины", label="Дисциплина")
    teacher = forms.ModelChoiceField(
        Teacher.objects.all(), required=False, empty_label="Все преподаватели", label="Преподаватель")
    only_free = forms.BooleanField(required=False, label="Только со свободными местами")
    date_from = forms.DateField(
        required=False, label="С даты", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(
        required=False, label="По дату", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end and start > end:
            self.add_error("date_to", "Дата «по» не может быть раньше даты «с».")
        return cleaned

    def apply_filters(self, queryset, data):
        # taken_count / free_count считаются одним запросом (без N+1 в шаблоне)
        queryset = queryset.annotate(taken_count=Count("submissions")).annotate(
            free_count=F("max_students") - F("taken_count"))
        if data.get("subject"):
            queryset = queryset.filter(subject=data["subject"])
        if data.get("teacher"):
            queryset = queryset.filter(teacher=data["teacher"])
        if data.get("only_free"):
            queryset = queryset.filter(taken_count__lt=F("max_students"))
        if data.get("date_from"):
            queryset = queryset.filter(date_time__date__gte=data["date_from"])
        if data.get("date_to"):
            queryset = queryset.filter(date_time__date__lte=data["date_to"])
        return queryset


# ключ сортировки (из заголовка колонки) -> поле модели
SUBMISSION_SORT_FIELDS = {
    "student": "student_name",
    "group": "group_name",
    "subject": "slot__subject__title",
    "slot": "slot__date_time",
    "lab": "lab_number",
    "status": "status",
    "created": "created_at",
}


class SubmissionFilterForm(ListFilterForm):
    """Поиск и фильтры таблицы записей. Сортировка — по клику на заголовок колонки."""
    SORTS = {}
    for _key, _field in SUBMISSION_SORT_FIELDS.items():
        SORTS[_key] = (_field, "pk")
        SORTS["-" + _key] = ("-" + _field, "-pk")
    del _key, _field
    DEFAULT_SORT = "slot"
    SEARCH_FIELDS = ("student_name", "group_name", "github_url", "slot__subject__title")
    PLACEHOLDER = "ФИО, группа, репозиторий, дисциплина"

    status = forms.ChoiceField(
        required=False, label="Статус",
        choices=[("", "Любой статус")] + Submission.STATUS_CHOICES)
    subject = forms.ModelChoiceField(
        Subject.objects.all(), required=False, empty_label="Все дисциплины", label="Дисциплина")
    lab_number = forms.IntegerField(
        required=False, min_value=1, max_value=20, label="Лабораторная №")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sort"].widget = forms.HiddenInput()  # меняется кликом по заголовку

    def apply_filters(self, queryset, data):
        if data.get("status"):
            queryset = queryset.filter(status=data["status"])
        if data.get("subject"):
            queryset = queryset.filter(slot__subject=data["subject"])
        if data.get("lab_number"):
            queryset = queryset.filter(lab_number=data["lab_number"])
        return queryset
