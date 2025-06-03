from django.urls import path

from .views import student_exam_details
from .views import upcoming_sessions

app_name = "exam"
urlpatterns = [
    path("upcoming/", upcoming_sessions, name="events-upcoming"),
    path("student/<int:student_id>/", student_exam_details, name="student-event"),
]
