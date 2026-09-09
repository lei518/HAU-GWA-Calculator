from django.urls import path
from . import views

app_name = "subjects"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("subjects/new/", views.subject_create, name="subject_create"),
    path("subjects/<int:pk>/", views.subject_detail, name="subject_detail"),
    path("subjects/<int:pk>/delete/", views.subject_delete, name="subject_delete"),
    path("subjects/<int:pk>/class-standing/add/", views.class_standing_add, name="class_standing_add"),
    path("subjects/<int:pk>/class-standing/<int:assessment_id>/delete/",
         views.class_standing_delete, name="class_standing_delete"),
    path("subjects/<int:pk>/major-exam/<str:period>/", views.major_exam_update, name="major_exam_update"),
    path("subjects/<int:pk>/recalculate/", views.recalculate, name="recalculate"),
    path("subjects/<int:pk>/target/", views.target_grade, name="target_grade"),
]
