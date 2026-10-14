from django.contrib import admin
from .models import Subject, Teacher, LabSlot, Submission


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'code')
    search_fields = ('title', 'code')

@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'telegram_chat_id')
    search_fields = ('full_name', 'email')

@admin.register(LabSlot)
class LabSlotAdmin(admin.ModelAdmin):
    list_display = ('subject', 'teacher', 'date_time', 'classroom', 'max_students')
    list_filter = ('subject', 'teacher', 'date_time')

@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'student_name',
        'group_name',
        'slot',
        'lab_number',
        'status',
        'created_at',
    )
    list_filter = ('status', 'group_name', 'slot__subject')
    search_fields = ('student_name', 'group_name')