# main/test_ajax_lists.py
"""Тесты ЛЗ 11: AJAX-обновление списков, удаление без перезагрузки, проверка «на лету»."""
import json

from django.contrib.messages import get_messages
from django.urls import reverse

from .models import Submission
from .test_lists import ListsBase

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class SlotListAjaxTests(ListsBase):
    def test_ajax_returns_fragment_not_full_page(self):
        r = self.client.get(reverse("slot_list"), **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "main/_slot_fragment.html")
        self.assertTemplateNotUsed(r, "main/base.html")
        for part in ('id="list-summary"', 'id="list-errors"', 'id="list-body"'):
            self.assertContains(r, part)
        self.assertNotContains(r, "<html")

    def test_normal_request_still_returns_full_page(self):
        r = self.client.get(reverse("slot_list"))
        self.assertTemplateUsed(r, "main/slot_list.html")
        self.assertContains(r, "<html")
        self.assertContains(r, "data-ajax-list")          # форма, которую перехватывает JS

    def test_both_variants_vary_on_ajax_header(self):
        """Кэш браузера не должен подменять полную страницу фрагментом и наоборот."""
        for extra in ({}, AJAX):
            r = self.client.get(reverse("slot_list"), **extra)
            self.assertIn("X-Requested-With", r["Vary"])

    def test_ajax_applies_search_and_filters(self):
        self.make_slots(2, subject=self.subject)
        self.make_slots(3, subject=self.subject2)
        r = self.client.get(reverse("slot_list"), {"q": "чкв"}, **AJAX)
        self.assertEqual(len(r.context["page_obj"]), 3)
        self.assertContains(r, "Показано 1–3 из 3")

    def test_ajax_does_not_count_as_page_visit_or_touch_cookie(self):
        self.client.get(reverse("slot_list"))
        r = self.client.get(reverse("slot_list"), **AJAX)
        self.assertEqual(self.client.session["visits"], 1)
        self.assertNotIn("last_visit", r.cookies)

    def test_ajax_shows_validation_errors(self):
        r = self.client.get(reverse("slot_list"), {"sort": "hack", "subject": "abc"}, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Выберите корректный вариант")

    def test_ajax_pagination_links_keep_parameters(self):
        self.make_slots(8)
        r = self.client.get(reverse("slot_list"), {"sort": "-date"}, **AJAX)
        self.assertContains(r, "sort=-date&amp;page=2")

    def test_ajax_empty_result_message(self):
        r = self.client.get(reverse("slot_list"), {"q": "такого нет"}, **AJAX)
        self.assertContains(r, "Ничего не найдено")
        self.assertContains(r, "По вашему запросу слотов нет")


class SubmissionListAjaxTests(ListsBase):
    def test_ajax_returns_fragment_with_table(self):
        self.make_submission()
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("submission_list"), **AJAX)
        self.assertTemplateUsed(r, "main/_submission_fragment.html")
        self.assertContains(r, 'id="list-body"')
        self.assertContains(r, "Иванов Иван")
        self.assertNotContains(r, "<html")

    def test_ajax_keeps_permissions_student_sees_only_own(self):
        self.make_submission(name="Иванов Иван")
        self.make_submission(user=self.other, name="Чужой Студент")
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("submission_list"), **AJAX)
        self.assertContains(r, "Иванов Иван")
        self.assertNotContains(r, "Чужой Студент")

    def test_ajax_sort_and_filter(self):
        self.make_submission(name="Борисов Борис", lab=2)
        self.make_submission(user=self.other, name="Андреев Андрей", lab=5)
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(reverse("submission_list"), {"sort": "student"}, **AJAX)
        self.assertEqual(self.sub_names(r), ["Андреев Андрей", "Борисов Борис"])
        r = self.client.get(reverse("submission_list"), {"lab_number": 5}, **AJAX)
        self.assertEqual(self.sub_names(r), ["Андреев Андрей"])

    def test_anonymous_ajax_is_redirected_to_login(self):
        r = self.client.get(reverse("submission_list"), **AJAX)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_delete_button_has_js_hooks_and_plain_link_fallback(self):
        sub = self.make_submission()
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("submission_list"))
        url = reverse("submission_delete", args=[sub.pk])
        self.assertContains(r, 'class="btn btn-sm btn-danger-soft js-delete"')
        self.assertContains(r, f'href="{url}"')            # без JS работает обычная ссылка
        self.assertContains(r, f'data-url="{url}"')
        self.assertContains(r, 'id="confirm-delete"')


class DeleteAjaxTests(ListsBase):
    def delete(self, sub, **extra):
        return self.client.post(reverse("submission_delete", args=[sub.pk]), **extra)

    def test_owner_deletes_via_ajax_and_gets_json(self):
        sub = self.make_submission()
        self.client.login(username="stud", password="pass12345!")
        r = self.delete(sub, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True, "message": "Запись удалена", "waiting": 0})
        self.assertFalse(Submission.objects.filter(pk=sub.pk).exists())
        self.assertEqual(list(get_messages(r.wsgi_request)), [])   # flash не нужен: страница не перезагружается

    def test_json_contains_updated_waiting_counter(self):
        first = self.make_submission(name="Иванов Иван")
        self.make_submission(name="Петров Пётр", lab=2)
        self.client.login(username="stud", password="pass12345!")
        self.assertEqual(self.delete(first, **AJAX).json()["waiting"], 1)

    def test_foreign_submission_gives_json_404_and_stays(self):
        sub = self.make_submission(user=self.other, name="Чужой Студент")
        self.client.login(username="stud", password="pass12345!")
        r = self.delete(sub, **AJAX)
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.json()["ok"])
        self.assertTrue(Submission.objects.filter(pk=sub.pk).exists())

    def test_teacher_can_delete_any_submission(self):
        sub = self.make_submission(user=self.other, name="Чужой Студент")
        self.client.login(username="teach", password="pass12345!")
        self.assertEqual(self.delete(sub, **AJAX).status_code, 200)
        self.assertFalse(Submission.objects.filter(pk=sub.pk).exists())

    def test_anonymous_cannot_delete(self):
        sub = self.make_submission()
        self.assertEqual(self.delete(sub, **AJAX).status_code, 302)
        self.assertTrue(Submission.objects.filter(pk=sub.pk).exists())

    def test_plain_post_still_redirects_with_flash_message(self):
        sub = self.make_submission()
        self.client.login(username="stud", password="pass12345!")
        r = self.delete(sub)
        self.assertRedirects(r, reverse("submission_list"))
        self.assertEqual([str(m) for m in get_messages(r.wsgi_request)], ["Запись удалена."])

    def test_status_change_returns_waiting_counter(self):
        first = self.make_submission(name="Иванов Иван")
        self.make_submission(name="Петров Пётр", lab=2)
        self.client.login(username="teach", password="pass12345!")
        r = self.client.post(reverse("submission_status", args=[first.pk]),
                             json.dumps({"status": "PASSED"}), content_type="application/json")
        self.assertEqual(r.json()["waiting"], 1)


class BookingCheckTests(ListsBase):
    def check(self, **params):
        return self.client.get(reverse("book_check", args=[self.slot.pk]), params, **AJAX)

    def test_duplicate_is_reported(self):
        self.make_submission(name="Иванов Иван", lab=3)
        self.client.login(username="other", password="pass12345!")
        d = self.check(student_name="иванов  иван", lab_number=3).json()   # регистр и пробелы не мешают
        self.assertEqual((d["ok"], d["checked"]), (False, True))
        self.assertIn("уже записан", d["message"])

    def test_free_combination_is_ok(self):
        self.make_submission(name="Иванов Иван", lab=3)
        self.client.login(username="other", password="pass12345!")
        d = self.check(student_name="Иванов Иван", lab_number=4).json()
        self.assertEqual((d["ok"], d["checked"]), (True, True))

    def test_incomplete_or_wrong_input_is_not_checked(self):
        self.client.login(username="other", password="pass12345!")
        for params in ({}, {"student_name": "Иванов", "lab_number": 3},
                       {"student_name": "Иванов Иван", "lab_number": "abc"},
                       {"student_name": "Иванов Иван", "lab_number": 99}):
            self.assertFalse(self.check(**params).json()["checked"], params)

    def test_requires_login_and_existing_slot(self):
        self.assertEqual(self.check(student_name="Иванов Иван", lab_number=3).status_code, 302)
        self.client.login(username="other", password="pass12345!")
        r = self.client.get(reverse("book_check", args=[99999]), **AJAX)
        self.assertEqual(r.status_code, 404)

    def test_server_still_validates_duplicates_on_submit(self):
        """Подсказка в браузере не заменяет проверку формы на сервере."""
        self.make_submission(name="Иванов Иван", lab=3)
        self.client.login(username="other", password="pass12345!")
        r = self.client.post(reverse("book_slot", args=[self.slot.pk]), {
            "student_name": "Иванов Иван", "group_name": "23-03", "lab_number": 3,
            "github_url": "https://github.com/a/b"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "уже записан")
        self.assertEqual(Submission.objects.count(), 1)


class PageMarkupTests(ListsBase):
    def test_book_page_has_hint_with_check_url(self):
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("book_slot", args=[self.slot.pk]))
        self.assertContains(r, 'id="booking-hint"')
        self.assertContains(r, reverse("book_check", args=[self.slot.pk]))

    def test_nav_badge_wrapper_exists_even_when_count_is_zero(self):
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("slot_list"))
        self.assertContains(r, 'id="nav-badge"')
        self.assertNotContains(r, "nav-count")
        self.make_submission()
        r = self.client.get(reverse("slot_list"))
        self.assertContains(r, 'class="nav-count"')

    def test_base_has_toast_container(self):
        self.assertContains(self.client.get(reverse("slot_list")), 'id="toast-box"')

    def test_waiting_for_counts_by_role(self):
        self.make_submission(name="Иванов Иван")
        self.make_submission(user=self.other, name="Другой Студент")
        self.assertEqual(Submission.waiting_for(self.student), 1)
        self.assertEqual(Submission.waiting_for(self.staff), 2)
