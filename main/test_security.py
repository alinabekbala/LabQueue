# main/test_security.py
"""Тесты ЛЗ 12: имитация атак (XSS, SQL Injection, CSRF, подмена id) и проверка защитных настроек."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.urls import reverse

from .models import Submission
from .test_lists import ListsBase

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
XSS = "<script>alert('XSS')</script>"
ROOT = Path(__file__).resolve().parent


class XssTests(ListsBase):
    """Угроза: чужой скрипт на странице. Защита: автоэкранирование шаблонов и textContent."""

    def book(self, name):
        return self.client.post(reverse("book_slot", args=[self.slot.pk]), {
            "student_name": name, "group_name": "23-03", "lab_number": 5,
            "github_url": "https://github.com/a/b"})

    def test_stored_xss_in_name_is_escaped_in_list(self):
        self.client.login(username="stud", password="pass12345!")
        self.book(f"{XSS} Иванов")
        r = self.client.get(reverse("submission_list"))
        self.assertNotContains(r, XSS)                               # сырого <script> нет
        self.assertContains(r, "&lt;script&gt;alert(&#x27;XSS&#x27;)&lt;/script&gt;")

    def test_stored_xss_is_escaped_in_ajax_fragment(self):
        self.client.login(username="stud", password="pass12345!")
        self.book(f"{XSS} Иванов")
        r = self.client.get(reverse("submission_list"), **AJAX)
        self.assertNotContains(r, "<script>")

    def test_reflected_xss_in_search_is_escaped(self):
        r = self.client.get(reverse("slot_list"), {"q": XSS})
        self.assertNotContains(r, XSS)
        r = self.client.get(reverse("slot_list"), {"q": XSS}, **AJAX)
        self.assertNotContains(r, XSS)

    def test_reflected_xss_in_invalid_parameters_is_escaped(self):
        for params in ({"page": XSS}, {"sort": XSS}, {"subject": XSS}, {"date_from": XSS}):
            r = self.client.get(reverse("slot_list"), params)
            self.assertNotContains(r, XSS, msg_prefix=str(params))

    def test_template_has_no_safe_or_autoescape_off(self):
        """В шаблонах нет |safe, mark_safe и {% autoescape off %}: экранирование не обходится."""
        for path in (ROOT / "templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\|\s*safe\b", msg=str(path))
            self.assertNotIn("autoescape off", text, msg=str(path))
        for path in ROOT.glob("*.py"):
            if path.name.startswith("test_") or path.name == "tests.py":
                continue
            self.assertNotIn("mark_safe", path.read_text(encoding="utf-8"), msg=str(path))

    def test_js_never_puts_user_text_into_inner_html(self):
        js = (ROOT / "static/main/js/dynamic.js").read_text(encoding="utf-8")
        code = "\n".join(l for l in js.splitlines() if not l.strip().startswith(("//", "*", "/*")))
        self.assertNotRegex(code, r"\.innerHTML\s*=")
        self.assertNotIn("insertAdjacentHTML", code)
        self.assertNotIn("document.write", code)


class SqlInjectionTests(ListsBase):
    """Угроза: ввод становится частью SQL. Защита: ORM, значения передаются параметрами."""

    PAYLOADS = ["' OR '1'='1", "'; DROP TABLE main_labslot; --", "\" OR 1=1 --", "%' OR 1=1 --"]

    def test_search_payloads_do_not_change_query_meaning(self):
        self.make_slots(3, subject=self.subject)
        total = self.client.get(reverse("slot_list")).context["page_obj"].paginator.count
        self.assertGreater(total, 0)
        for payload in self.PAYLOADS:
            r = self.client.get(reverse("slot_list"), {"q": payload})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.context["page_obj"].paginator.count, 0, msg=payload)   # не «все строки»
        self.assertEqual(self.client.get(reverse("slot_list")).context["page_obj"].paginator.count, total)

    def test_submission_search_payloads_do_not_leak_other_students_rows(self):
        self.client.login(username="stud", password="pass12345!")
        for payload in self.PAYLOADS:
            r = self.client.get(reverse("submission_list"), {"q": payload})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.context["page_obj"].paginator.count, 0, msg=payload)

    def test_sort_parameter_is_whitelisted(self):
        r = self.client.get(reverse("slot_list"), {"sort": "date; DROP TABLE main_labslot"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("sort", r.context["form"].errors)

    def test_no_raw_sql_in_project(self):
        for path in ROOT.glob("*.py"):
            if path.name.startswith("test_") or path.name == "tests.py":
                continue
            text = path.read_text(encoding="utf-8")
            for bad in (".raw(", ".extra(", "RawSQL", "cursor.execute"):
                self.assertNotIn(bad, text, msg=f"{path.name}: {bad}")


class CsrfTests(ListsBase):
    """Угроза: чужой сайт действует от имени вошедшего. Защита: токен, SameSite, изменения только POST."""

    def setUp(self):
        super().setUp()
        self.strict = Client(enforce_csrf_checks=True)            # настоящая проверка токена, как в браузере
        self.strict.login(username="stud", password="pass12345!")

    def test_post_without_token_is_forbidden(self):
        sub = self.make_submission()
        r = self.strict.post(reverse("submission_delete", args=[sub.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Submission.objects.filter(pk=sub.pk).exists())

    def test_ajax_post_without_token_is_forbidden(self):
        sub = self.make_submission()
        r = self.strict.post(reverse("submission_delete", args=[sub.pk]), **AJAX)
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Submission.objects.filter(pk=sub.pk).exists())

    def test_ajax_post_with_header_token_works(self):
        sub = self.make_submission()
        page = self.strict.get(reverse("submission_list"))
        token = re.search(r'name="csrf-token" content="([^"]+)"', page.content.decode()).group(1)
        r = self.strict.post(reverse("submission_delete", args=[sub.pk]), HTTP_X_CSRFTOKEN=token, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Submission.objects.filter(pk=sub.pk).exists())

    def test_every_post_form_has_csrf_token(self):
        for path in (ROOT / "templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for form in re.findall(r"<form[^>]*method=\"post\"[^>]*>.*?</form>", text, re.S | re.I):
                self.assertIn("{% csrf_token %}", form, msg=str(path))

    def test_csrf_protection_is_not_disabled(self):
        self.assertIn("django.middleware.csrf.CsrfViewMiddleware", settings.MIDDLEWARE)
        for path in ROOT.glob("*.py"):
            if path.name.startswith("test_") or path.name == "tests.py":
                continue
            self.assertNotIn("csrf_exempt", path.read_text(encoding="utf-8"), msg=str(path))

    def test_changes_are_not_possible_with_get(self):
        sub = self.make_submission()
        self.client.login(username="stud", password="pass12345!")
        self.client.get(reverse("submission_delete", args=[sub.pk]))      # GET только показывает подтверждение
        self.assertTrue(Submission.objects.filter(pk=sub.pk).exists())
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)   # выход только POST
        self.assertEqual(self.client.get(reverse("state_reset")).status_code, 405)

    def test_cookie_flags(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")


class AccessControlTests(ListsBase):
    """Угроза: доступ к чужим данным подменой id. Защита: роль и владелец проверяются на сервере."""

    def test_guest_is_redirected_to_login(self):
        sub = self.make_submission()
        for name, args in (("submission_list", []), ("submission_update", [sub.pk]),
                           ("submission_delete", [sub.pk]), ("book_slot", [self.slot.pk])):
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 302, msg=name)
            self.assertIn(reverse("login"), r["Location"])

    def test_foreign_id_gives_404_for_view_edit_delete(self):
        sub = self.make_submission(user=self.other)
        self.client.login(username="stud", password="pass12345!")
        self.assertEqual(self.client.get(reverse("submission_update", args=[sub.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("submission_update", args=[sub.pk]), {
            "student_name": "Взлом Взломов", "group_name": "x", "lab_number": 1,
            "github_url": "https://github.com/a/b"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("submission_delete", args=[sub.pk])).status_code, 404)
        sub.refresh_from_db()
        self.assertEqual(sub.student_name, "Иванов Иван")

    def test_foreign_and_missing_id_look_the_same(self):
        """Чужая запись неотличима от несуществующей: нельзя «перебирать» id и узнавать, что есть."""
        sub = self.make_submission(user=self.other)
        self.client.login(username="stud", password="pass12345!")
        foreign = self.client.get(reverse("submission_update", args=[sub.pk]))
        missing = self.client.get(reverse("submission_update", args=[999999]))
        self.assertEqual(foreign.status_code, missing.status_code)

    def test_list_contains_only_own_rows_even_with_forged_parameters(self):
        self.make_submission(user=self.other, name="Чужой Студент")
        self.make_submission(user=self.student, name="Свой Студент", lab=2)
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("submission_list"), {"student": self.other.pk, "student_id": self.other.pk,
                                                          "q": "Чужой"})
        self.assertEqual(r.context["page_obj"].paginator.count, 0)
        self.assertNotContains(r, "Чужой Студент")

    def test_student_cannot_set_status_even_by_direct_request(self):
        sub = self.make_submission()
        self.client.login(username="stud", password="pass12345!")
        r = self.client.post(reverse("submission_status", args=[sub.pk]),
                             json.dumps({"status": "PASSED"}), content_type="application/json")
        self.assertEqual(r.status_code, 403)
        # и через обычную форму редактирования поле status студенту просто не приходит
        self.client.post(reverse("submission_update", args=[sub.pk]), {
            "student_name": "Иванов Иван", "group_name": "23-03", "lab_number": 1,
            "github_url": "https://github.com/a/b", "status": "PASSED"})
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.STATUS_WAITING)

    def test_student_cannot_open_teacher_pages(self):
        self.client.login(username="stud", password="pass12345!")
        for name in ("slot_create",):
            self.assertIn(self.client.get(reverse(name)).status_code, (302, 403))
        self.assertIn(self.client.get(reverse("slot_update", args=[self.slot.pk])).status_code, (302, 403))
        self.assertIn(self.client.post(reverse("slot_delete", args=[self.slot.pk])).status_code, (302, 403))
        self.assertTrue(type(self.slot).objects.filter(pk=self.slot.pk).exists())

    def test_open_redirect_is_blocked(self):
        r = self.client.get(reverse("set_theme", args=["dark"]), {"next": "https://evil.example/"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(r["Location"].startswith("https://evil"))


class ServerSideValidationTests(ListsBase):
    """Проверка в браузере (min/max, type=url) легко обходится: сервер проверяет всё заново."""

    def post(self, **over):
        data = {"student_name": "Иванов Иван", "group_name": "23-03", "lab_number": 3,
                "github_url": "https://github.com/a/b", **over}
        self.client.login(username="stud", password="pass12345!")
        return self.client.post(reverse("book_slot", args=[self.slot.pk]), data)

    def test_direct_post_with_bad_values_is_rejected(self):
        for over in ({"lab_number": 999}, {"lab_number": -5}, {"lab_number": "abc"},
                     {"github_url": "javascript:alert(1)"}, {"github_url": "https://evil.com/x"},
                     {"student_name": "Иванов"}, {"student_name": ""}, {"group_name": "x" * 500}):
            before = Submission.objects.count()
            r = self.post(**over)
            self.assertEqual(r.status_code, 200, msg=str(over))          # форма вернулась с ошибками
            self.assertEqual(Submission.objects.count(), before, msg=str(over))

    def test_bad_json_gives_400_not_500(self):
        sub = self.make_submission()
        self.client.login(username="teach", password="pass12345!")
        for body in ("{bad", "[]", '{"status": "HACKED"}', ""):
            r = self.client.post(reverse("submission_status", args=[sub.pk]), body, content_type="application/json")
            self.assertEqual(r.status_code, 400, msg=body)


class SecurityHeadersAndSettingsTests(ListsBase):
    def test_security_headers_present(self):
        r = self.client.get(reverse("slot_list"))
        csp = r["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self' https://cdn.jsdelivr.net", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-eval", csp)
        script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
        self.assertNotIn("unsafe-inline", script_src)            # встроенные скрипты запрещены
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_no_inline_scripts_in_templates(self):
        """CSP запрещает встроенные скрипты, значит в шаблонах их быть не должно."""
        for path in (ROOT / "templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for tag in re.findall(r"<script\b[^>]*>", text):
                self.assertIn("src=", tag, msg=f"{path}: {tag}")
            self.assertNotRegex(text, r"\son[a-z]+\s*=\s*[\"']", msg=str(path))   # onclick= и т. п.

    def test_error_pages_do_not_leak_details(self):
        self.client.login(username="stud", password="pass12345!")
        r = self.client.get(reverse("submission_update", args=[424242]))
        self.assertEqual(r.status_code, 404)
        self.assertNotContains(r, "Traceback", status_code=404)

    def test_secret_key_comes_from_environment(self):
        text = (Path(settings.BASE_DIR) / "mysite" / "settings.py").read_text(encoding="utf-8")
        self.assertIn("os.environ.get('DJANGO_SECRET_KEY'", text)
        self.assertIn("SECURE_HSTS_SECONDS", text)
        self.assertIn("SESSION_COOKIE_SECURE", text)
