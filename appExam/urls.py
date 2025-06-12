from django.urls import path

from .views import get_exam_review
from .views import get_exam_session_view
from .views import get_paginated_questions_view
from .views import get_question_list_view
from .views import submit_active_exam
from .views import submit_answer_view

app_name = "exam"
urlpatterns = [
    path("session/", get_exam_session_view, name="get_exam_session"),
    path("questions/", get_paginated_questions_view, name="get_paginated_questions"),
    path("list/questions/", get_question_list_view, name="list_questions"),
    path("answer/submit/", submit_answer_view, name="submit_answer"),
    path("review/", get_exam_review, name="exam_review"),
    path("session/end/", submit_active_exam, name="end_exam"),
]
