from django.urls import path

from . import views

urlpatterns = [
    # Candidate URLs
    path(
        "candidate/register/", views.candidate_register_view, name="candidate_register"
    ),
    path("candidate/login/", views.candidate_login_view, name="candidate_login"),
    path("initial/info/",views.closest_session_view,name="intial-info"),
]
