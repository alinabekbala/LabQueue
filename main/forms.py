from django import forms
from .models import Submission


class SubmissionForm(forms.ModelForm):

    class Meta:
        model = Submission
        fields = [
            'student_name',
            'group_name',
            'lab_number',
            'github_url',
            'status',  # Поле для выбора статуса (UPDATE)
        ]
        widgets = {
            'student_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Например: Бекбала Алина',
                }
            ),
            'group_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Например: CS-2101',
                }
            ),
            'lab_number': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Номер лабы (1-10)',
                    'min': 1,
                }
            ),
            'github_url': forms.URLInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'https://github.com/username/repo',
                }
            ),
            'status': forms.Select(
                attrs={
                    'class': 'form-select',  # Красивый стилизованный Bootstrap-селект
                }
            ),
        }
        labels = {
            'student_name': 'ФИО студента',
            'group_name': 'Учебная группа',
            'lab_number': 'Номер лабораторной работы',
            'github_url': 'Ссылка на GitHub / GitLab',
            'status': 'Статус проверки',
        }