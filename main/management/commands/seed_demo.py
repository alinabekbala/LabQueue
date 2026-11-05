# main/management/commands/seed_demo.py
"""Команда `python manage.py seed_demo` — заполняет БД демонстрационными данными."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from main.models import LabSlot, Subject, Submission, Teacher


class Command(BaseCommand):
    help = "Создаёт демо-данные: дисциплины, преподавателей, слоты и тестовых пользователей"

    def add_arguments(self, parser):
        parser.add_argument(
            "--many", action="store_true",
            help="ЛЗ 10: добавить много слотов и записей, чтобы были видны поиск, фильтры и пагинация")

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

        if options["many"]:
            self.seed_many()

        self.stdout.write(self.style.SUCCESS(
            "Готово. Преподаватель: teacher / teacher12345, студент: student / student12345"))

    def seed_many(self):
        """Дополнительные данные для демонстрации списков (повторный запуск ничего не дублирует)."""
        subjects = list(Subject.objects.all())
        teachers = list(Teacher.objects.all())
        if LabSlot.objects.count() >= 20:
            return
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        rooms = ["Ауд. 101", "Ауд. 214", "Ауд. 305", "Ауд. 112", "Zoom (ссылка в чате)", "Ауд. 410"]
        slots = []
        for i in range(24):
            slot = LabSlot.objects.create(
                subject=subjects[i % len(subjects)], teacher=teachers[i % len(teachers)],
                date_time=(now + timedelta(days=i // 2 + 1)).replace(hour=9 + (i % 5) * 2),
                classroom=rooms[i % len(rooms)], max_students=2 + i % 5)
            slots.append(slot)

        names = ["Ахметов Данияр", "Серикова Айгерим", "Нурланов Тимур", "Касымова Алия",
                 "Жумабеков Арман", "Оспанова Мадина", "Исмаилов Руслан", "Токтарова Динара",
                 "Бекова Сабина", "Мукашев Ерлан", "Абдрахманова Томирис", "Сатыбалдиев Али"]
        statuses = [Submission.STATUS_WAITING, Submission.STATUS_PASSED, Submission.STATUS_REJECTED]
        for n, full_name in enumerate(names, start=1):
            user, created = User.objects.get_or_create(
                username=f"stud{n:02d}", defaults={"email": f"stud{n:02d}@example.com"})
            if created:
                user.set_password("student12345")
                user.save()
            for k in range(4):
                slot = slots[(n * 2 + k * 5) % len(slots)]
                if slot.is_full:
                    continue
                Submission.objects.create(
                    slot=slot, student=user, student_name=full_name,
                    group_name=["23-01", "23-02", "23-03", "22-05"][n % 4],
                    lab_number=1 + (n + k * 3) % 9,
                    github_url=f"https://github.com/stud{n:02d}/lab{1 + (n + k * 3) % 9}",
                    status=statuses[(n + k) % 3])
