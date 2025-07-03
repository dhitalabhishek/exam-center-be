# appCore/routing.py

from django.urls import re_path


def get_websocket_urlpatterns():
    from .consumer.status import ExamStatusConsumer
    return [
        re_path(r"ws/exam/status/$", ExamStatusConsumer.as_asgi()),
    ]
