from django.urls import path

from .flows_view import AdminWizardView

urlpatterns = [
    path("wizard/", AdminWizardView.as_view(), name="exam_wizard"),
    path(
        "wizard/<int:step>/",
        AdminWizardView.as_view(),
        name="exam_wizard_step",
    ),
]
