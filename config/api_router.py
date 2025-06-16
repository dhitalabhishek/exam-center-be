# config/api_router.py

from django.conf import settings
from django.urls import include
from django.urls import path
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from appAuthentication.serializers import CandidateLoginSerializer
from appAuthentication.views import candidate_login_view

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

custom_urls = [
    # Candidate login
    path(
        "login/student/",
        extend_schema(
            methods=["POST"],
            request=CandidateLoginSerializer,
            responses={
                200: OpenApiResponse(description="Candidate logged in successfully"),
                400: OpenApiResponse(description="Validation errors"),
                401: OpenApiResponse(description="Invalid symbol number or password"),
            },
        )(candidate_login_view),
        name="candidate-login",
    ),
    # Institutions “upcoming events” and “student event” endpoints
    # path(
    #     "institutions/",
    #     include(("appInstitutions.urls", "institutions"), namespace="institutions"),  # noqa: E501, ERA001
    # ),

    # Exam specific endpoints (“events/upcoming” and “events/student/<id>”)
    path("exam/", include(("appExam.urls", "exam"), namespace="exam")),
    path("core/",include(("appCore.urls","core"),namespace="core")),
]

app_name = "api"
urlpatterns = custom_urls + router.urls
