from django.urls import path

from .views import trigger_fake_task

app_name = "appTest"

urlpatterns = [
    path("", trigger_fake_task, name="fakeTask"),
]
