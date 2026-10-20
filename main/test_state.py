# main/test_state.py
"""Автотесты ЛЗ 8: сессии и cookies. Запуск: python manage.py test main.test_state"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import state
from .models import LabSlot, Subject, Teacher

PASSWORD = "pass12345!"
BOOKING = {"student_name": "Бекбала Алина", "group_name": "23-03",
           "lab_number": 3, "github_url": "https://github.com/a/b"}


class StateTestCase(TestCase):
    def setUp(self):
        self.web = Subject.objects.create(title="Веб")
        self.hci = Subject.objects.create(title="ЧКВ")
        self.teacher = Teacher.objects.create(full_name="Иманбек Р.К.", email="t@e.kz")
        soon = timezone.now() + timedelta(days=1)
        self.slot = LabSlot.objects.create(subject=self.web, teacher=self.teacher,
                                           date_time=soon, classroom="305", max_students=5)
        self.slot2 = LabSlot.objects.create(subject=self.hci, teacher=self.teacher,
                                            date_time=soon, classroom="112", max_students=5)
        self.user = User.objects.create_user("stud", "s@e.kz", PASSWORD)

    def login(self):
        self.client.login(username="stud", password=PASSWORD)


class SessionTests(StateTestCase):
    def test_filter_is_saved_and_restored(self):
        self.client.get(reverse("slot_list"), {"subject": self.hci.id})
        resp = self.client.get(reverse("slot_list"))      # без параметра
        self.assertEqual(resp.context["selected"], str(self.hci.id))
        self.assertTrue(resp.context["filter_restored"])
        self.assertEqual([s.id for s in resp.context["slots"]], [self.slot2.id])

    def test_empty_filter_resets_saved_value(self):
        self.client.get(reverse("slot_list"), {"subject": self.hci.id})
        self.client.get(reverse("slot_list"), {"subject": ""})
        resp = self.client.get(reverse("slot_list"))
        self.assertEqual(len(resp.context["slots"]), 2)
        self.assertFalse(resp.context["filter_restored"])

    def test_garbage_filter_is_ignored(self):
        resp = self.client.get(reverse("slot_list"), {"subject": "abc"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["slots"]), 2)
        self.assertNotIn(state.SESSION_FILTER, self.client.session)

    def test_visit_counter_grows(self):
        for expected in (1, 2, 3):
            resp = self.client.get(reverse("slot_list"))
            self.assertEqual(resp.context["visits"], expected)

    def test_viewed_slots_recorded_without_duplicates(self):
        self.login()
        self.client.get(reverse("book_slot", args=[self.slot.id]))
        self.client.get(reverse("book_slot", args=[self.slot2.id]))
        self.client.get(reverse("book_slot", args=[self.slot.id]))
        self.assertEqual(self.client.session[state.SESSION_VIEWED], [self.slot.id, self.slot2.id])
        resp = self.client.get(reverse("slot_list"))
        self.assertEqual([s.id for s in resp.context["recent_slots"]], [self.slot.id, self.slot2.id])

    def test_viewed_slots_limit(self):
        session = self.client.session
        for i in range(1, 9):
            state.remember_viewed_slot(session, i)
        self.assertEqual(session[state.SESSION_VIEWED], [8, 7, 6, 5, 4])

    def test_profile_saved_after_booking_and_prefilled(self):
        self.login()
        self.client.post(reverse("book_slot", args=[self.slot.id]), BOOKING)
        self.assertEqual(self.client.session[state.SESSION_PROFILE],
                         {"student_name": "Бекбала Алина", "group_name": "23-03"})
        resp = self.client.get(reverse("book_slot", args=[self.slot2.id]))
        self.assertEqual(resp.context["form"].initial["student_name"], "Бекбала Алина")
        self.assertTrue(resp.context["prefilled"])

    def test_session_is_isolated_between_clients(self):
        self.client.get(reverse("slot_list"), {"subject": self.hci.id})
        other = self.client_class()
        resp = other.get(reverse("slot_list"))
        self.assertEqual(resp.context["selected"], "")


class CookieTests(StateTestCase):
    def test_theme_cookie_is_set(self):
        resp = self.client.get(reverse("set_theme", args=["dark"]))
        self.assertRedirects(resp, reverse("slot_list"))
        cookie = resp.cookies[state.THEME_COOKIE]
        self.assertEqual(cookie.value, "dark")
        self.assertEqual(cookie["max-age"], state.THEME_MAX_AGE)
        self.assertEqual(cookie["samesite"], "Lax")

    def test_theme_is_applied_to_html(self):
        self.client.cookies[state.THEME_COOKIE] = "dark"
        html = self.client.get(reverse("slot_list")).content.decode()
        self.assertIn('data-theme="dark"', html)

    def test_invalid_theme_cookie_falls_back_to_light(self):
        self.client.cookies[state.THEME_COOKIE] = "<script>"
        html = self.client.get(reverse("slot_list")).content.decode()
        self.assertIn('data-theme="light"', html)
        self.assertNotIn("<script>alert", html)

    def test_unknown_theme_is_404(self):
        self.assertEqual(self.client.get(reverse("set_theme", args=["pink"])).status_code, 404)

    def test_next_url_must_be_local(self):
        resp = self.client.get(reverse("set_theme", args=["dark"]), {"next": "https://evil.com/"})
        self.assertRedirects(resp, reverse("slot_list"))
        resp = self.client.get(reverse("set_theme", args=["dark"]), {"next": "/state/"})
        self.assertRedirects(resp, "/state/")

    def test_last_visit_cookie(self):
        first = self.client.get(reverse("slot_list"))
        self.assertIsNone(first.context["last_visit"])
        self.assertIn(state.LAST_VISIT_COOKIE, first.cookies)
        second = self.client.get(reverse("slot_list"))
        self.assertIsNotNone(second.context["last_visit"])

    def test_broken_last_visit_cookie_is_ignored(self):
        self.client.cookies[state.LAST_VISIT_COOKIE] = "not-a-number"
        self.assertIsNone(self.client.get(reverse("slot_list")).context["last_visit"])


class RememberMeTests(StateTestCase):
    def test_without_flag_session_ends_with_browser(self):
        self.client.post(reverse("login"), {"username": "stud", "password": PASSWORD})
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_with_flag_session_lives_30_days(self):
        self.client.post(reverse("login"),
                         {"username": "stud", "password": PASSWORD, "remember_me": "on"})
        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertGreater(session.get_expiry_age(), state.REMEMBER_ME_AGE - 60)


class StatePageTests(StateTestCase):
    def test_page_is_available_and_hides_secrets(self):
        self.login()
        resp = self.client.get(reverse("state"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn(self.client.cookies["sessionid"].value, html)
        self.assertIn("sessionid", html)

    def test_reset_clears_app_data_but_keeps_login(self):
        self.login()
        self.client.get(reverse("slot_list"), {"subject": self.hci.id})
        resp = self.client.post(reverse("state_reset"))
        self.assertRedirects(resp, reverse("state"))
        self.assertNotIn(state.SESSION_FILTER, self.client.session)
        self.assertEqual(resp.cookies[state.LAST_VISIT_COOKIE].value, "")
        self.assertEqual(self.client.get(reverse("submission_list")).status_code, 200)

    def test_reset_requires_post(self):
        self.assertEqual(self.client.get(reverse("state_reset")).status_code, 405)
