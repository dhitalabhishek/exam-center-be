# appCore/routing.py

from django.urls import re_path


def get_websocket_urlpatterns():
    from .consumer import exam  # Delayed import
    return [
        re_path(r"ws/exam/$", exam.ExamConsumer.as_asgi()),
    ]
