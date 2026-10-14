# main/tests.py
"""Автотесты: запуск `python manage.py test`."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import SubmissionForm
from .models import LabSlot, Subject, Submission, Teacher


class BaseTestCase(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(title="Веб")
        self.subject2 = Subject.objects.create(title="ЧКВ")
        self.teacher = Teacher.objects.create(full_name="Иманбек Р.К.", email="t@e.kz")
        self.slot = LabSlot.objects.create(
            subject=self.subject, teacher=self.teacher,
            date_time=timezone.now() + timedelta(days=1),
            classroom="305", max_students=2)
        self.student = User.objects.create_user("stud", "s@e.kz", "pass12345!")
        self.other = User.objects.create_user("other", "o@e.kz", "pass12345!")
        self.staff = User.objects.create_user("teach", "t@e.kz", "pass12345!", is_staff=True)

    def make_submission(self, user=None, name="Иванов Иван", lab=1):
        return Submission.objects.create(
            slot=self.slot, student=user or self.student, student_name=name,
            group_name="23-03", lab_number=lab, github_url="https://github.com/a/b")


class ModelTests(BaseTestCase):
    def test_slot_counts_and_full(self):
        self.assertFalse(self.slot.is_full)
        self.make_submission(name="Иванов Иван")
        self.make_submission(name="Петров Пётр")
        self.assertTrue(self.slot.is_full)

    def test_cascade_delete(self):
        self.make_submission()
        self.slot.delete()
        self.assertEqual(Submission.objects.count(), 0)


class FormTests(BaseTestCase):
    data = {"student_name": "Бекбала Алина", "group_name": "23-03",
            "lab_number": 3, "github_url": "https://github.com/a/b"}

    def test_valid(self):
        self.assertTrue(SubmissionForm(self.data, slot=self.slot).is_valid())

    def test_foreign_host_rejected(self):
        form = SubmissionForm({**self.data, "github_url": "https://evil.com/x"}, slot=self.slot)
        self.assertIn("github_url", form.errors)

    def test_lab_number_range(self):
        form = SubmissionForm({**self.data, "lab_number": 99}, slot=self.slot)
        self.assertIn("lab_number", form.errors)

    def test_full_slot_rejected(self):
        self.make_submission(name="Иванов Иван")
        self.make_submission(name="Петров Пётр")
        self.assertFalse(SubmissionForm(self.data, slot=self.slot).is_valid())

    def test_duplicate_rejected(self):
        self.make_submission(name="Бекбала Алина", lab=3)
        self.assertFalse(SubmissionForm(self.data, slot=self.slot).is_valid())

    def test_student_has_no_status_field(self):
        self.assertNotIn("status", SubmissionForm(slot=self.slot).fields)
        self.assertIn("status", SubmissionForm(slot=self.slot, is_teacher=True).fields)


class ViewTests(BaseTestCase):
    def test_slot_list_public_and_filter(self):
        LabSlot.objects.create(subject=self.subject2, teacher=self.teacher,
                               date_time=timezone.now() + timedelta(days=2), classroom="1")
        self.assertEqual(self.client.get(reverse("slot_list")).status_code, 200)
        resp = self.client.get(reverse("slot_list"), {"subject": self.subject2.id})
        self.assertEqual(len(resp.context["slots"]), 1)

    def test_booking_requires_login(self):
        resp = self.client.get(reverse("book_slot", args=[self.slot.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_student_books_slot(self):
        self.client.login(username="stud", password="pass12345!")
        resp = self.client.post(reverse("book_slot", args=[self.slot.id]), {
            "student_name": "Бекбала Алина", "group_name": "23-03",
            "lab_number": 3, "github_url": "https://github.com/a/b"})
        self.assertRedirects(resp, reverse("submission_list"))
        sub = Submission.objects.get()
        self.assertEqual(sub.student, self.student)
        self.assertEqual(sub.status, Submission.STATUS_WAITING)

    def test_student_cannot_edit_foreign_submission(self):
        sub = self.make_submission(user=self.other)
        self.client.login(username="stud", password="pass12345!")
        self.assertEqual(self.client.get(reverse("submission_update", args=[sub.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("submission_delete", args=[sub.pk])).status_code, 403)

    def test_student_sees_only_own(self):
        self.make_submission(user=self.other)
        self.client.login(username="stud", password="pass12345!")
        self.assertEqual(len(self.client.get(reverse("submission_list")).context["submissions"]), 0)

    def test_teacher_changes_status_and_deletes(self):
        sub = self.make_submission()
        self.client.login(username="teach", password="pass12345!")
        self.client.post(reverse("submission_update", args=[sub.pk]), {
            "student_name": "Иванов Иван", "group_name": "23-03", "lab_number": 1,
            "github_url": "https://github.com/a/b", "status": "PASSED"})
        sub.refresh_from_db()
        self.assertEqual(sub.status, "PASSED")
        self.client.post(reverse("submission_delete", args=[sub.pk]))
        self.assertFalse(Submission.objects.exists())

    def test_slot_crud_only_for_teacher(self):
        self.client.login(username="stud", password="pass12345!")
        self.assertEqual(self.client.get(reverse("slot_create")).status_code, 302)
        self.client.login(username="teach", password="pass12345!")
        self.assertEqual(self.client.get(reverse("slot_create")).status_code, 200)

    def test_register_creates_student_and_logs_in(self):
        resp = self.client.post(reverse("register"), {
            "username": "newbie", "email": "n@e.kz",
            "password1": "Str0ng-pass-77", "password2": "Str0ng-pass-77"})
        self.assertRedirects(resp, reverse("slot_list"))
        user = User.objects.get(username="newbie")
        self.assertFalse(user.is_staff)
