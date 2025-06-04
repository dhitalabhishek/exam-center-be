from django.apps import apps
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.generic import TemplateView


@method_decorator(staff_member_required, name="dispatch")
@method_decorator(xframe_options_exempt, name="dispatch")
class AdminWizardView(TemplateView):
    template_name = "admin/wizard.html"

    # Define your model flow here - just the app_label.model_name
    WIZARD_FLOW = [
        ("appInstitutions.Institute", "Institute Setup"),
        ("appAuthentication.Candidate", "Candidate Management"),
        ("appInstitutions.Program", "Program Configuration"),
        ("appExam.Exam", "Exam Setup"),
        ("appExam.ExamSession", "Exam Session"),
        ("appExam_app.Question", "Question Management"),
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get current step from URL or default to first
        current_step = kwargs.get("step", 0)
        try:
            current_step = int(current_step)
        except (ValueError, TypeError):
            current_step = 0

        if current_step >= len(self.WIZARD_FLOW):
            current_step = 0

        # Get model info
        model_path, title = self.WIZARD_FLOW[current_step]
        app_label, model_name = model_path.split(".")
        model = apps.get_model(app_label, model_name)

        # Build admin URL
        admin_url = f"/admin/{app_label}/{model_name.lower()}/"

        context.update({
            "current_step": current_step,
            "total_steps": len(self.WIZARD_FLOW),
            "step_title": title,
            "model": model,
            "admin_url": admin_url,
            "has_previous": current_step > 0,
            "has_next": current_step < len(self.WIZARD_FLOW) - 1,
            "previous_step": current_step - 1 if current_step > 0 else None,
            "next_step": current_step + 1 if current_step < len(self.WIZARD_FLOW) - 1 else None,  # noqa: E501
            "all_steps": [
                {
                    "index": i,
                    "title": step[1],
                    "is_current": i == current_step,
                }
                for i, step in enumerate(self.WIZARD_FLOW)
            ],
            "progress": ((current_step + 1) / len(self.WIZARD_FLOW)) * 100,
        })

        return context

