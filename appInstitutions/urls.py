# from django.urls import path  # noqa: ERA001

# from .views import student_event_info  # noqa: ERA001
# from .views import upcoming_events  # noqa: ERA001

app_name = "institutions"


# no routes defined for now we will route these if we need
# instutions specific urls in future with {"institutions"} namespace
urlpatterns = [
    # path("events/upcoming/", upcoming_events, name="upcoming-events"),  # noqa: ERA001
    # path("events/student/<int:student_id>/", student_event_info, name="student-event-info"),  # noqa: E501, ERA001
]
