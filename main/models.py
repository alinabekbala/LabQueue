# lab_booking/models.py
from django.db import models
from django.core.validators import URLValidator

class Subject(models.Model):
    """Дисциплина"""
    title = models.CharField(max_length=200, verbose_name="Название дисциплины")
    code = models.CharField(max_length=20, verbose_name="Код дисциплины", blank=True, null=True)

    class Meta:
        verbose_name = "Дисциплина"
        verbose_name_plural = "Дисциплины"

    def __str__(self):
        return self.title


class Teacher(models.Model):
    """Преподаватель"""
    full_name = models.CharField(max_length=150, verbose_name="ФИО преподавателя")
    email = models.EmailField(verbose_name="Email")
    telegram_chat_id = models.CharField(max_length=50, verbose_name="Telegram Chat ID", blank=True, null=True)

    class Meta:
        verbose_name = "Преподаватель"
        verbose_name_plural = "Преподаватели"

    def __str__(self):
        return self.full_name


class LabSlot(models.Model):
    """Слот для защиты лабораторных"""
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="slots", verbose_name="Дисциплина")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="slots", verbose_name="Преподаватель")
    date_time = models.DateTimeField(verbose_name="Дата и время начала")
    classroom = models.CharField(max_length=50, verbose_name="Аудитория / Ссылка на созвон")
    max_students = models.PositiveIntegerField(default=5, verbose_name="Макс. количество студентов")

    class Meta:
        verbose_name = "Слот защиты"
        verbose_name_plural = "Слоты защиты"
        ordering = ['date_time']

    def __str__(self):
        return f"{self.subject.title} | {self.date_time.strftime('%d.%m %H:%M')} ({self.classroom})"


class Submission(models.Model):
    """Запись студента на защиту"""
    STATUS_CHOICES = [
        ('WAITING', 'Ожидает защиты'),
        ('PASSED', 'Зачтено'),
        ('REJECTED', 'На доработку'),
    ]

    slot = models.ForeignKey(LabSlot, on_delete=models.CASCADE, related_name="submissions", verbose_name="Слот")
    student_name = models.CharField(max_length=150, verbose_name="ФИО студента")
    group_name = models.CharField(max_length=50, verbose_name="Учебная группа")
    lab_number = models.PositiveIntegerField(verbose_name="Номер лабораторной")
    github_url = models.URLField(validators=[URLValidator()], verbose_name="Ссылка на GitHub/GitLab")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING', verbose_name="Статус")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата записи")

    class Meta:
        verbose_name = "Запись на защиту"
        verbose_name_plural = "Записи на защиту"

    def __str__(self):
        return f"{self.student_name} ({self.group_name}) - Лаба №{self.lab_number}"