# main/models.py
"""Модели (таблицы БД) проекта LabQueue.

Связи:
    Subject 1 --- N LabSlot      (у дисциплины много слотов)
    Teacher 1 --- N LabSlot      (у преподавателя много слотов)
    LabSlot 1 --- N Submission   (на слот записано много студентов)
    User    1 --- N Submission   (студент-пользователь оставляет много записей)
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Subject(models.Model):
    """Дисциплина"""
    title = models.CharField("Название дисциплины", max_length=200)
    code = models.CharField("Код дисциплины", max_length=20, blank=True)
    description = models.TextField("Описание", blank=True)

    class Meta:
        verbose_name = "Дисциплина"
        verbose_name_plural = "Дисциплины"
        ordering = ["title"]

    def __str__(self):
        return self.title


class Teacher(models.Model):
    """Преподаватель"""
    full_name = models.CharField("ФИО преподавателя", max_length=150)
    email = models.EmailField("Email")
    telegram_chat_id = models.CharField(
        "Telegram Chat ID", max_length=50, blank=True
    )

    class Meta:
        verbose_name = "Преподаватель"
        verbose_name_plural = "Преподаватели"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class LabSlot(models.Model):
    """Слот для защиты лабораторных"""
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Дисциплина",
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE,
        related_name="slots", verbose_name="Преподаватель",
    )
    date_time = models.DateTimeField("Дата и время начала")
    classroom = models.CharField("Аудитория / ссылка на созвон", max_length=200)
    max_students = models.PositiveIntegerField(
        "Макс. количество студентов", default=5,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
    )

    class Meta:
        verbose_name = "Слот защиты"
        verbose_name_plural = "Слоты защиты"
        ordering = ["date_time"]

    def __str__(self):
        return f"{self.subject.title} | {self.date_time:%d.%m %H:%M} ({self.classroom})"

    @property
    def taken(self):
        """Сколько мест занято (используем аннотацию, если она есть)."""
        if hasattr(self, "taken_count"):
            return self.taken_count
        return self.submissions.count()

    @property
    def is_full(self):
        return self.taken >= self.max_students

    @property
    def free_places(self):
        """Сколько мест ещё свободно (не меньше нуля)."""
        return max(self.max_students - self.taken, 0)


class Submission(models.Model):
    """Запись студента на защиту"""
    STATUS_WAITING = "WAITING"
    STATUS_PASSED = "PASSED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (STATUS_WAITING, "Ожидает защиты"),
        (STATUS_PASSED, "Зачтено"),
        (STATUS_REJECTED, "На доработку"),
    ]

    slot = models.ForeignKey(
        LabSlot, on_delete=models.CASCADE,
        related_name="submissions", verbose_name="Слот",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="submissions", verbose_name="Пользователь",
    )
    student_name = models.CharField("ФИО студента", max_length=150)
    group_name = models.CharField("Учебная группа", max_length=50)
    lab_number = models.PositiveIntegerField(
        "Номер лабораторной",
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    github_url = models.URLField("Ссылка на GitHub / GitLab")
    status = models.CharField(
        "Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_WAITING
    )
    created_at = models.DateTimeField("Дата записи", auto_now_add=True)

    class Meta:
        verbose_name = "Запись на защиту"
        verbose_name_plural = "Записи на защиту"
        ordering = ["slot__date_time", "created_at"]

    def __str__(self):
        return f"{self.student_name} ({self.group_name}) — лаба №{self.lab_number}"
