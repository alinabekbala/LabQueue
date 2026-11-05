# main/test_lists.py
"""Тесты ЛЗ 10: поиск, фильтры, сортировка и пагинация списков."""
from datetime import timedelta

from django.db import connection
from django.template import Context, Template
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .apps import _unicode_like
from .models import LabSlot, Submission, Teacher
from .tests import BaseTestCase


class ListsBase(BaseTestCase):
    def make_slots(self, count, **kwargs):
        slots = []
        for i in range(count):
            slots.append(LabSlot.objects.create(
                subject=kwargs.get("subject", self.subject),
                teacher=kwargs.get("teacher", self.teacher),
                date_time=timezone.now() + timedelta(days=2 + i),
                classroom=f"Ауд. {100 + i}", max_students=kwargs.get("max_students", 3)))
        return slots

    def slot_ids(self, response):
        return [s.pk for s in response.context["page_obj"]]

    def sub_names(self, response):
        return [s.student_name for s in response.context["page_obj"]]


class UnicodeLikeTests(ListsBase):
    def test_like_is_case_insensitive_for_cyrillic(self):
        self.assertEqual(_unicode_like("%иманбек%", "Иманбек Р.К."), 1)
        self.assertEqual(_unicode_like("%ВЕБ%", "Разработка веб-приложений"), 1)
        self.assertEqual(_unicode_like("%ложка%", "Иманбек"), 0)

    def test_like_wildcards_and_escape(self):
        self.assertEqual(_unicode_like("ab_", "abc"), 1)
        self.assertEqual(_unicode_like("a\\%b", "a%b", "\\"), 1)
        self.assertEqual(_unicode_like("a\\%b", "axb", "\\"), 0)

    def test_like_null(self):
        self.assertIsNone(_unicode_like(None, "x"))


class SlotSearchFilterTests(ListsBase):
    url = property(lambda self: reverse("slot_list"))

    def test_search_by_subject_case_insensitive(self):
        r = self.client.get(self.url, {"q": "веб"})
        self.assertEqual(self.slot_ids(r), [self.slot.pk])
        r = self.client.get(self.url, {"q": "ВЕБ"})
        self.assertEqual(self.slot_ids(r), [self.slot.pk])

    def test_search_by_teacher_name_lowercase(self):
        r = self.client.get(self.url, {"q": "иманбек"})
        self.assertEqual(self.slot_ids(r), [self.slot.pk])

    def test_search_by_classroom(self):
        r = self.client.get(self.url, {"q": "305"})
        self.assertEqual(self.slot_ids(r), [self.slot.pk])

    def test_all_words_must_match(self):
        self.assertEqual(self.slot_ids(self.client.get(self.url, {"q": "веб иманбек"})), [self.slot.pk])
        self.assertEqual(self.slot_ids(self.client.get(self.url, {"q": "веб несуществует"})), [])

    def test_nothing_found_message(self):
        r = self.client.get(self.url, {"q": "zzzz"})
        self.assertContains(r, "По вашему запросу слотов нет")
        self.assertContains(r, "Ничего не найдено")

    def test_filter_by_subject_and_teacher(self):
        other_teacher = Teacher.objects.create(full_name="Сабитов Н.", email="s@e.kz")
        s2 = self.make_slots(1, subject=self.subject2, teacher=other_teacher)[0]
        r = self.client.get(self.url, {"subject": self.subject2.pk})
        self.assertEqual(self.slot_ids(r), [s2.pk])
        r = self.client.get(self.url, {"teacher": other_teacher.pk})
        self.assertEqual(self.slot_ids(r), [s2.pk])
        r = self.client.get(self.url, {"subject": self.subject.pk, "teacher": other_teacher.pk})
        self.assertEqual(self.slot_ids(r), [])

    def test_only_free_excludes_full_slots(self):
        self.make_submission(self.student, lab=1)
        self.make_submission(self.other, lab=2)            # слот на 2 места заполнен
        free = self.make_slots(1)[0]
        r = self.client.get(self.url, {"only_free": "on"})
        self.assertEqual(self.slot_ids(r), [free.pk])

    def test_date_range(self):
        later = self.make_slots(1)[0]                     # через 2 дня
        far = timezone.localdate() + timedelta(days=30)
        r = self.client.get(self.url, {"date_from": far.isoformat()})
        self.assertEqual(self.slot_ids(r), [])
        r = self.client.get(self.url, {"date_to": (timezone.localdate() + timedelta(days=1)).isoformat()})
        self.assertEqual(self.slot_ids(r), [self.slot.pk])
        self.assertNotIn(later.pk, self.slot_ids(r))

    def test_reversed_date_range_shows_error(self):
        r = self.client.get(self.url, {"date_from": "2030-01-10", "date_to": "2030-01-01"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "не может быть раньше")

    def test_sort_by_date_desc_and_free(self):
        later = self.make_slots(1, max_students=9)[0]
        r = self.client.get(self.url, {"sort": "-date"})
        self.assertEqual(self.slot_ids(r), [later.pk, self.slot.pk])
        r = self.client.get(self.url, {"sort": "free"})
        self.assertEqual(self.slot_ids(r), [later.pk, self.slot.pk])   # 9 свободных > 2

    def test_unknown_sort_falls_back_to_default(self):
        later = self.make_slots(1)[0]
        r = self.client.get(self.url, {"sort": "date_time; DROP TABLE main_labslot"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.slot_ids(r), [self.slot.pk, later.pk])
        self.assertEqual(r.context["current_sort"], "date")

    def test_garbage_filter_values_do_not_crash(self):
        r = self.client.get(self.url, {"subject": "abc", "teacher": "-1", "date_from": "xx", "page": "zz"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.slot_ids(r), [self.slot.pk])      # мусор проигнорирован

    def test_injection_like_query_is_just_text(self):
        r = self.client.get(self.url, {"q": "'; DROP TABLE main_labslot; --"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(LabSlot.objects.count(), 1)

    def test_subject_filter_still_remembered_in_session(self):
        self.client.get(self.url, {"subject": self.subject2.pk})
        r = self.client.get(self.url)                          # без параметра: берём из сессии
        self.assertTrue(r.context["filter_restored"])
        self.assertEqual(r.context["selected"], str(self.subject2.pk))
        r = self.client.get(self.url, {"subject": ""})         # сброс
        self.assertEqual(r.context["selected"], "")


class SlotPaginationTests(ListsBase):
    url = property(lambda self: reverse("slot_list"))

    def setUp(self):
        super().setUp()
        self.make_slots(13)                                    # вместе с исходным слотом — 14

    def test_six_per_page_and_three_pages(self):
        r = self.client.get(self.url)
        page = r.context["page_obj"]
        self.assertEqual(len(page), 6)
        self.assertEqual(page.paginator.num_pages, 3)
        self.assertContains(r, "Показано 1–6 из 14")

    def test_last_page_has_rest(self):
        r = self.client.get(self.url, {"page": 3})
        self.assertEqual(len(r.context["page_obj"]), 2)

    def test_wrong_page_numbers_are_safe(self):
        self.assertEqual(self.client.get(self.url, {"page": 99}).context["page_obj"].number, 3)
        self.assertEqual(self.client.get(self.url, {"page": "abc"}).context["page_obj"].number, 1)
        # номер вне диапазона (в том числе отрицательный) -> последняя страница
        self.assertEqual(self.client.get(self.url, {"page": -5}).context["page_obj"].number, 3)

    def test_pages_do_not_overlap(self):
        ids = []
        for n in (1, 2, 3):
            ids += self.slot_ids(self.client.get(self.url, {"page": n}))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 14)

    def test_links_keep_search_and_sort(self):
        r = self.client.get(self.url, {"q": "веб", "sort": "-date"})
        self.assertContains(r, "page=2")
        html = r.content.decode()
        link = [part for part in html.split('href="') if part.startswith("?") and "page=2" in part][0]
        self.assertIn("q=", link)
        self.assertIn("sort=-date", link)

    def test_no_pagination_for_single_page(self):
        r = self.client.get(self.url, {"q": "305"})
        self.assertNotContains(r, 'aria-label="Страницы"')

    def test_query_count_does_not_grow_with_rows(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(self.url)
            return len(ctx)
        before = count()
        self.make_slots(10)
        self.assertEqual(count(), before)


class SubmissionListTests(ListsBase):
    url = property(lambda self: reverse("submission_list"))

    def setUp(self):
        super().setUp()
        self.slot_big = self.make_slots(1, subject=self.subject2, max_students=50)[0]

    def add(self, name, lab=1, status=Submission.STATUS_WAITING, user=None, slot=None, group="23-03"):
        return Submission.objects.create(
            slot=slot or self.slot_big, student=user or self.student, student_name=name,
            group_name=group, lab_number=lab, github_url=f"https://github.com/x/{name[:3]}", status=status)

    def test_student_sees_only_own_even_when_searching_others(self):
        self.add("Иванов Иван", user=self.student)
        self.add("Петров Пётр", user=self.other)
        self.client.login(username="stud", password="pass12345!")
        self.assertEqual(self.sub_names(self.client.get(self.url)), ["Иванов Иван"])
        self.assertEqual(self.sub_names(self.client.get(self.url, {"q": "Петров"})), [])

    def test_teacher_searches_all(self):
        self.add("Иванов Иван")
        self.add("Петров Пётр", user=self.other, group="22-05")
        self.client.login(username="teach", password="pass12345!")
        self.assertEqual(self.sub_names(self.client.get(self.url, {"q": "иванов"})), ["Иванов Иван"])
        self.assertEqual(self.sub_names(self.client.get(self.url, {"q": "22-05"})), ["Петров Пётр"])

    def test_filters_status_subject_lab(self):
        self.add("А Один", lab=1, status=Submission.STATUS_PASSED)
        self.add("Б Два", lab=2)
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(self.url, {"status": "PASSED"})
        self.assertEqual(self.sub_names(r), ["А Один"])
        r = self.client.get(self.url, {"lab_number": 2})
        self.assertEqual(self.sub_names(r), ["Б Два"])
        r = self.client.get(self.url, {"subject": self.subject.pk})
        self.assertEqual(self.sub_names(r), [])

    def test_sort_by_column_both_directions(self):
        self.add("Бета Б", lab=5)
        self.add("Альфа А", lab=9)
        self.add("Гамма Г", lab=2)
        self.client.login(username="teach", password="pass12345!")
        self.assertEqual(self.sub_names(self.client.get(self.url, {"sort": "student"})),
                         ["Альфа А", "Бета Б", "Гамма Г"])
        self.assertEqual(self.sub_names(self.client.get(self.url, {"sort": "-lab"})),
                         ["Альфа А", "Бета Б", "Гамма Г"])
        self.assertEqual(self.sub_names(self.client.get(self.url, {"sort": "lab"})),
                         ["Гамма Г", "Бета Б", "Альфа А"])

    def test_sort_whitelist(self):
        self.add("Бета Б")
        self.client.login(username="teach", password="pass12345!")
        for bad in ("password", "student_name", "slot__student__password", "-id; --"):
            r = self.client.get(self.url, {"sort": bad})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.context["current_sort"], "slot")

    def test_header_link_toggles_direction(self):
        self.add("Бета Б")
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(self.url, {"sort": "lab"})
        self.assertContains(r, "sort=-lab")           # повторный клик — по убыванию
        self.assertContains(r, "▲")
        r = self.client.get(self.url, {"sort": "-lab"})
        self.assertContains(r, "▼")

    def test_invalid_status_shows_error_not_crash(self):
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(self.url, {"status": "HACK", "lab_number": "99"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "bi-exclamation-circle")

    def test_pagination_ten_per_page(self):
        for i in range(25):
            self.add(f"Студент {i:02d}", lab=1 + i % 9)
        self.client.login(username="teach", password="pass12345!")
        r = self.client.get(self.url, {"sort": "student"})
        self.assertEqual(len(r.context["page_obj"]), 10)
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 3)
        r = self.client.get(self.url, {"sort": "student", "page": 3})
        self.assertEqual(self.sub_names(r), [f"Студент {i:02d}" for i in range(20, 25)])
        self.assertContains(r, "Показано 21–25 из 25")

    def test_empty_states(self):
        self.client.login(username="stud", password="pass12345!")
        self.assertContains(self.client.get(self.url), "Записей пока нет")
        self.assertContains(self.client.get(self.url, {"q": "нет такого"}), "По вашему запросу записей нет")

    def test_query_count_does_not_grow_with_rows(self):
        self.client.login(username="teach", password="pass12345!")
        for i in range(12):
            self.add(f"Студент {i:02d}")

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(self.url)
            return len(ctx)
        before = count()
        for i in range(12, 30):
            self.add(f"Студент {i:02d}")
        self.assertEqual(count(), before)


class QualityTests(ListsBase):
    def test_equal_sort_keys_keep_stable_order(self):
        """Слоты с одинаковым числом мест и временем идут в одном и том же порядке (по pk)."""
        when = timezone.now() + timedelta(days=5)
        a = LabSlot.objects.create(subject=self.subject, teacher=self.teacher, date_time=when,
                                   classroom="A", max_students=4)
        b = LabSlot.objects.create(subject=self.subject, teacher=self.teacher, date_time=when,
                                   classroom="B", max_students=4)
        for _ in range(3):
            r = self.client.get(reverse("slot_list"), {"sort": "free"})
            ids = self.slot_ids(r)
            self.assertLess(ids.index(a.pk), ids.index(b.pk))

    def test_no_pending_migrations(self):
        from django.core.management import call_command
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)

    def test_indexes_exist(self):
        with connection.cursor() as cursor:
            names = {c.name for c in connection.introspection.get_constraints(cursor, "main_submission").values()
                     if False} or set(connection.introspection.get_constraints(cursor, "main_submission"))
        self.assertTrue({"sub_status_idx", "sub_lab_idx"} <= names)


class TemplateTagTests(ListsBase):
    def render(self, template, query):
        request = RequestFactory().get("/", query)
        return Template("{% load slot_tags %}" + template).render(Context({"request": request}))

    def test_url_replace_keeps_other_params(self):
        out = self.render("{% url_replace page=3 %}", {"q": "веб", "sort": "free", "page": "1"})
        self.assertIn("page=3", out)
        self.assertIn("sort=free", out)
        self.assertIn("q=", out)

    def test_url_replace_removes_empty_value(self):
        out = self.render("{% url_replace page='' %}", {"q": "a", "page": "2"})
        self.assertNotIn("page", out)
