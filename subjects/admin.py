from django.contrib import admin
from .models import ClassStandingAssessment, MajorExam, Subject

class ClassStandingAssessmentInline(admin.TabularInline):
    model = ClassStandingAssessment
    extra = 0

class MajorExamInline(admin.TabularInline):
    model = MajorExam
    extra = 0

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "student", "units", "passing_average")
    inlines = [ClassStandingAssessmentInline, MajorExamInline]

@admin.register(ClassStandingAssessment)
class ClassStandingAssessmentAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "grading_period", "score", "highest_possible_score")
    list_filter = ("grading_period",)

@admin.register(MajorExam)
class MajorExamAdmin(admin.ModelAdmin):
    list_display = ("subject", "grading_period", "score", "highest_possible_score", "weight")
    list_filter = ("grading_period",)
