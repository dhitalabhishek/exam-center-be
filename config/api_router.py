from django.conf import settings
from django.urls import path
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from appAuthentication.serializers import CandidateLoginSerializer
from appAuthentication.views import candidate_login_view

# from backend.users.api.views import UserViewSet
# router.register("users", UserViewSet)

# Use DefaultRouter in DEBUG (for browsable API), SimpleRouter otherwise
router = DefaultRouter() if settings.DEBUG else SimpleRouter()
# e.g. router.register("users", UserViewSet)

app_name = "api"

custom_urls = [
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
]


urlpatterns = custom_urls + router.urls
