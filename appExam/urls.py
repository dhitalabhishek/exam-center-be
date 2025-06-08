from django.urls import path

from .views import get_exam_session_view
from .views import get_paginated_questions_view
from .views import submit_answer_view

# from .views import student_exam_details
# from .views import upcoming_sessions

app_name = "exam"
urlpatterns = [
    path("session/", get_exam_session_view, name="get_exam_session"),
    path("questions/", get_paginated_questions_view, name="get_paginated_questions"),
    path("answer/submit/", submit_answer_view, name="submit_answer"),
    # path("upcoming/", upcoming_sessions, name="events-upcoming"),
    # path("student/<int:student_id>/", student_exam_details, name="student-event"),
]
