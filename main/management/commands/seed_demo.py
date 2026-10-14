# main/management/commands/seed_demo.py
"""Команда `python manage.py seed_demo` — заполняет БД демонстрационными данными."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from main.models import LabSlot, Subject, Submission, Teacher


class Command(BaseCommand):
    help = "Создаёт демо-данные: дисциплины, преподавателей, слоты и тестовых пользователей"

    def handle(self, *args, **options):
        web, _ = Subject.objects.get_or_create(
            title="Разработка веб-приложений", defaults={"code": "WEB301",
            "description": "Django, ORM, шаблоны, формы"})
        hci, _ = Subject.objects.get_or_create(
            title="Человеко-компьютерное взаимодействие", defaults={"code": "HCI201"})
        cuda, _ = Subject.objects.get_or_create(
            title="Организация параллельных вычислений", defaults={"code": "GPU401"})

        imanbek, _ = Teacher.objects.get_or_create(
            full_name="Иманбек Р.К.", defaults={"email": "imanbek@example.com"})
        assist, _ = Teacher.objects.get_or_create(
            full_name="Ассистент Сабитов Н.", defaults={"email": "assistant@example.com"})

        if not LabSlot.objects.exists():
            now = timezone.now().replace(minute=0, second=0, microsecond=0)
            data = [
                (web, imanbek, 1, 10, "Ауд. 305", 5),
                (web, imanbek, 2, 12, "Ауд. 305", 3),
                (hci, assist, 2, 15, "Zoom (ссылка в чате)", 4),
                (cuda, assist, 3, 11, "Ауд. 112", 6),
            ]
            for subject, teacher, days, hour, room, cap in data:
                dt = (now + timedelta(days=days)).replace(hour=hour)
                LabSlot.objects.create(subject=subject, teacher=teacher,
                                       date_time=dt, classroom=room, max_students=cap)

        teacher_user, created = User.objects.get_or_create(
            username="teacher", defaults={"is_staff": True, "is_superuser": True,
                                          "email": "teacher@example.com",
                                          "first_name": "Иманбек"})
        if created:
            teacher_user.set_password("teacher12345")
            teacher_user.save()

        student, created = User.objects.get_or_create(
            username="student", defaults={"email": "student@example.com"})
        if created:
            student.set_password("student12345")
            student.save()
            slot = LabSlot.objects.first()
            Submission.objects.create(
                slot=slot, student=student, student_name="Бекбала Алина Ерлановна",
                group_name="23-03", lab_number=3,
                github_url="https://github.com/example/lab3")

        self.stdout.write(self.style.SUCCESS(
            "Готово. Преподаватель: teacher / teacher12345, студент: student / student12345"))
