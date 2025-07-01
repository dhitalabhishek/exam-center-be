from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include
from django.urls import path
from django.views import defaults as default_views

# from django.views.generic import TemplateView  # noqa: ERA001
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView

from appAuthentication.utils.ajax_views import check_admin_second_password
from appAuthentication.utils.biometric_view import get_candidate_details
from appAuthentication.utils.biometric_view import webcam_capture_view
from appCore.views import log_view
from appCore.views import mark_notification_read
from appCore.views import notification_fragment

admin.site.site_header = "Exam Admin"
admin.site.site_title = "Admin"
admin.site.index_title = "Dashboard"


urlpatterns = [
    path("silk/", include("silk.urls", namespace="silk")),
    # Core pages
    # path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),  # noqa: E501, ERA001
    # path("about/", TemplateView.as_view(template_name="pages/about.html"), name="about"),  # noqa: E501, ERA001
    # Admin
        path("check-second-password/", check_admin_second_password, name="check_second_password"),  # noqa: E501

    path(
        f"{settings.ADMIN_URL}flows/exam-creation/",
        include("appCore.flows.flow_1_handelingExamCreation.flows_urls"),
    ),

    # URL FOR AJAX CALLBACK
    path(
        "biometric/candidate-details/",
        get_candidate_details,
        name="get_candidate_details",
    ),
    path(
        "biometric/verification/",
        admin.site.admin_view(webcam_capture_view),
        name="biometric-verification",
    ),
    path("admin/notifications/fragment/", notification_fragment,name="admin_notifications_fragment"),  # noqa: E501
    path("admin/notifications/read/<int:pk>/", mark_notification_read, name="admin_notifications_read"),  # noqa: E501

    path("admin/logs/", log_view, name="log_view"),

    path(settings.ADMIN_URL, admin.site.urls),

    # Monitoring
    path("", include("django_prometheus.urls")),
    # App includes
    # path("users/", include("backend.users.urls", namespace="users")),  # noqa: ERA001
    # path("accounts/", include("appAuthentication.urls")),  # noqa: ERA001
    # API
    path("api/", include("config.api_router")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
]

# Development only
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]

    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls)), *urlpatterns]
