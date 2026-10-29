# main/test_dynamic.py
"""Тесты ЛЗ 9: компоненты (partial, inclusion_tag, фильтры) и AJAX-события."""
import json

from django.db import connection
from django.template import Context, Template
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import LabSlot, Submission
from .tests import BaseTestCase


class TemplateFilterTests(BaseTestCase):
    def render(self, value):
        return Template("{% load slot_tags %}{{ v|ru_places }}").render(Context({"v": value}))

    def test_ru_places_declension(self):
        cases = {1: "1 место", 2: "2 места", 4: "4 места", 5: "5 мест",
                 11: "11 мест", 12: "12 мест", 21: "21 место", 0: "0 мест"}
        for number, expected in cases.items():
            self.assertEqual(self.render(number), expected)

    def test_ru_places_bad_value_is_returned_as_is(self):
        self.assertEqual(self.render("abc"), "abc")


class ComponentTests(BaseTestCase):
    def test_slot_card_partial_is_rendered_on_list(self):
        r = self.client.get(reverse("slot_list"))
        self.assertTemplateUsed(r, "main/_slot_card.html")
        self.assertTemplateUsed(r, "main/_slot_cards.html")
        self.assertContains(r, "Свободно: 2 места")

    def test_empty_state_when_no_slots(self):
        self.slot.delete()
        r = self.client.get(reverse("slot_list"))
        self.assertContains(r, "Слотов пока нет")

    def test_top_free_component_shows_slot_with_free_places(self):
        r = self.client.get(reverse("slot_list"))
        self.assertTemplateUsed(r, "main/_top_free.html")
        self.assertContains(r, "Больше всего свободных мест")

    def test_top_free_component_hides_full_slots(self):
        self.make_submission(self.student, lab=1)
        self.make_submission(self.other, lab=2)       # слот на 2 места заполнен
        r = self.client.get(reverse("slot_list"))
        self.assertNotContains(r, "Больше всего свободных мест")
        self.assertContains(r, "Мест нет")

    def test_nav_badge_hidden_for_guest(self):
        r = self.client.get(reverse("slot_list"))
        self.assertNotContains(r, "nav-count")

    def test_nav_badge_counts_own_waiting_submissions_for_student(self):
        self.make_submission(self.student)
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("slot_list"))
        self.assertContains(r, 'class="nav-count"')

    def test_nav_badge_for_teacher_counts_all_waiting(self):
        self.make_submission(self.student)
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(reverse("slot_list"))
        self.assertContains(r, "Записей ждёт проверки")

    def test_role_based_buttons(self):
        r = self.client.get(reverse("slot_list"))
        self.assertNotContains(r, reverse("slot_update", args=[self.slot.pk]))
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(reverse("slot_list"))
        self.assertContains(r, reverse("slot_update", args=[self.slot.pk]))

    def test_no_n_plus_one_on_slot_list(self):
        """Число запросов не растёт с числом слотов (нет N+1 в цикле шаблона)."""
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse("slot_list"))
            return len(ctx)

        before = count_queries()
        for i in range(6):
            LabSlot.objects.create(
                subject=self.subject, teacher=self.teacher, date_time=self.slot.date_time,
                classroom=f"A{i}", max_students=3)
        self.assertEqual(count_queries(), before)


class SeatsJsonTests(BaseTestCase):
    def test_returns_json_with_counts(self):
        self.make_submission()
        r = self.client.get(reverse("slot_seats", args=[self.slot.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"taken": 1, "max": 2, "free": 1, "is_full": False})

    def test_full_slot(self):
        self.make_submission(self.student, lab=1)
        self.make_submission(self.other, lab=2)
        self.assertTrue(self.client.get(reverse("slot_seats", args=[self.slot.pk])).json()["is_full"])

    def test_unknown_slot_404(self):
        self.assertEqual(self.client.get(reverse("slot_seats", args=[9999])).status_code, 404)

    def test_book_page_has_live_counter(self):
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("book_slot", args=[self.slot.pk]))
        self.assertContains(r, 'id="seats-live"')
        self.assertContains(r, reverse("slot_seats", args=[self.slot.pk]))


class StatusAjaxTests(BaseTestCase):
    def post(self, sub, payload, raw=False):
        url = reverse("submission_status", args=[sub.pk])
        body = payload if raw else json.dumps(payload)
        return self.client.post(url, body, content_type="application/json")

    def test_teacher_changes_status(self):
        sub = self.make_submission()
        self.client.login(username="teach", password="pass12345!")
        r = self.post(sub, {"status": "PASSED"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True, "status": "PASSED", "label": "Зачтено"})
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.STATUS_PASSED)

    def test_student_gets_403_and_status_unchanged(self):
        sub = self.make_submission()
        self.client.login(username="stud", password="pass12345!")
        self.assertEqual(self.post(sub, {"status": "PASSED"}).status_code, 403)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.STATUS_WAITING)

    def test_guest_gets_403(self):
        sub = self.make_submission()
        self.assertEqual(self.post(sub, {"status": "PASSED"}).status_code, 403)

    def test_unknown_status_400(self):
        sub = self.make_submission()
        self.client.login(username="teach", password="pass12345!")
        self.assertEqual(self.post(sub, {"status": "HACK"}).status_code, 400)

    def test_bad_json_400(self):
        sub = self.make_submission()
        self.client.login(username="teach", password="pass12345!")
        self.assertEqual(self.post(sub, "{not json", raw=True).status_code, 400)

    def test_get_not_allowed(self):
        sub = self.make_submission()
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(reverse("submission_status", args=[sub.pk]))
        self.assertEqual(r.status_code, 405)

    def test_csrf_is_enforced(self):
        from django.test import Client
        sub = self.make_submission()
        c = Client(enforce_csrf_checks=True)
        c.login(username="teach", password="pass12345!")
        r = c.post(reverse("submission_status", args=[sub.pk]),
                   json.dumps({"status": "PASSED"}), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_status_select_only_for_teacher(self):
        sub = self.make_submission()
        url = reverse("submission_status", args=[sub.pk])
        self.client.login(username="stud", password="pass12345!")
        self.assertNotContains(self.client.get(reverse("submission_list")), url)
        self.client.logout()
        self.client.login(username="teach", password="pass12345!")
        self.assertContains(self.client.get(reverse("submission_list")), url)


class StaticAssetsTests(BaseTestCase):
    def test_script_and_csrf_meta_in_base(self):
        r = self.client.get(reverse("slot_list"))
        self.assertContains(r, "main/js/dynamic.js")
        self.assertContains(r, 'name="csrf-token"')
