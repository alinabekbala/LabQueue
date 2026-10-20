# main/forms.py
"""Формы: превращают модели в HTML-формы и проверяют данные на сервере."""
from urllib.parse import urlparse

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import LabSlot, Submission

ALLOWED_GIT_HOSTS = {"github.com", "www.github.com", "gitlab.com", "www.gitlab.com"}


class BootstrapMixin:
    """Добавляет Bootstrap-классы всем полям формы."""

    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


class LoginForm(BootstrapMixin, AuthenticationForm):
    """Форма входа. Флажок «Запомнить меня» управляет сроком жизни сессии (ЛЗ 8)."""
    remember_me = forms.BooleanField(
        required=False, label="Запомнить меня на 30 дней",
        help_text="Без флажка вход действует до закрытия браузера.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self.fields["username"].label = "Логин"
        self.fields["password"].label = "Пароль"


class RegisterForm(BootstrapMixin, UserCreationForm):
    """Форма регистрации студента (логин, email, пароль)."""
    email = forms.EmailField(label="Email", required=True)

    class Meta:
        model = User
        fields = ("username", "email")
        labels = {"username": "Логин"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Пароль"
        self.fields["password2"].label = "Повторите пароль"
        self._style_fields()

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class SubmissionForm(BootstrapMixin, forms.ModelForm):
    """Запись на защиту.

    Студент заполняет данные; поле «статус» доступно только преподавателю
    (is_teacher=True). Слот и пользователь передаются из view.
    """

    class Meta:
        model = Submission
        fields = ["student_name", "group_name", "lab_number", "github_url", "status"]
        widgets = {
            "student_name": forms.TextInput(attrs={"placeholder": "Например: Бекбала Алина Ерлановна"}),
            "group_name": forms.TextInput(attrs={"placeholder": "Например: 23-03"}),
            "lab_number": forms.NumberInput(attrs={"placeholder": "1–20", "min": 1, "max": 20}),
            "github_url": forms.URLInput(attrs={"placeholder": "https://github.com/user/repo"}),
        }

    def __init__(self, *args, slot=None, user=None, is_teacher=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.slot = slot or (self.instance.slot if self.instance.pk else None)
        self.user = user
        if not is_teacher:
            del self.fields["status"]
        self._style_fields()

    def clean_github_url(self):
        url = self.cleaned_data["github_url"]
        host = (urlparse(url).hostname or "").lower()
        if host not in ALLOWED_GIT_HOSTS:
            raise forms.ValidationError("Ссылка должна вести на github.com или gitlab.com.")
        return url

    def clean_student_name(self):
        name = " ".join(self.cleaned_data["student_name"].split())
        if len(name.split()) < 2:
            raise forms.ValidationError("Укажите фамилию и имя полностью.")
        return name

    def clean(self):
        cleaned = super().clean()
        slot = self.slot
        if slot is None:
            return cleaned
        others = slot.submissions.exclude(pk=self.instance.pk)
        # 1) лимит мест (только при создании записи)
        if not self.instance.pk and others.count() >= slot.max_students:
            raise forms.ValidationError("На этот слот больше нет свободных мест.")
        # 2) нельзя сдавать одну и ту же лабу дважды на одном слоте
        name, lab = cleaned.get("student_name"), cleaned.get("lab_number")
        if name and lab and others.filter(student_name__iexact=name, lab_number=lab).exists():
            raise forms.ValidationError(
                "Этот студент уже записан на этот слот с этой лабораторной."
            )
        return cleaned


class LabSlotForm(BootstrapMixin, forms.ModelForm):
    """Создание и редактирование слота (для преподавателя)."""

    class Meta:
        model = LabSlot
        fields = ["subject", "teacher", "date_time", "classroom", "max_students"]
        widgets = {
            "date_time": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "classroom": forms.TextInput(attrs={"placeholder": "Ауд. 305 или ссылка на Zoom"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_time"].input_formats = ["%Y-%m-%dT%H:%M"]
        self._style_fields()

    def clean_date_time(self):
        value = self.cleaned_data["date_time"]
        if not self.instance.pk and value < timezone.now():
            raise forms.ValidationError("Нельзя создать слот в прошлом.")
        return value

    def clean_max_students(self):
        value = self.cleaned_data["max_students"]
        if self.instance.pk and value < self.instance.submissions.count():
            raise forms.ValidationError(
                "Лимит не может быть меньше числа уже записанных студентов."
            )
        return value
