from django.contrib import admin
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import path

from .models import Candidate
from .models import Institute
from .models import User
from .tasks import process_candidates_csv


class CustomUserAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "is_staff",
        "is_admin",
        "is_candidate",
        "last_login",
    )
    list_filter = (
        "is_staff",
        "is_admin",
        "is_candidate",
    )
    search_fields = ("email",)


admin.site.register(User, CustomUserAdmin)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("symbol_number", "first_name", "last_name", "get_institute_name","program_id")
    search_fields = ("symbol_number", "first_name", "last_name")
    list_filter = ("institute",)

    def get_institute_name(self, obj):
        return obj.institute.name if obj.institute else "No Institute"

    get_institute_name.short_description = "Institute"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_import_button"] = True
        # Add institutes to the context for the modal
        extra_context["institutes"] = Institute.objects.all()
        return super().changelist_view(request, extra_context)

    # Add CSV import functionality to CandidateAdmin
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_candidates_csv),
                name="appAuthentication_candidate_import_csv",
            ),
        ]
        return custom_urls + urls

    def import_candidates_csv(self, request):
        # Get institute_id from GET parameters
        institute_id = request.GET.get("institute_id")
        selected_institute = None

        # Validate institute if provided
        if institute_id:
            try:
                selected_institute = Institute.objects.get(id=institute_id)
            except Institute.DoesNotExist:
                messages.error(request, "Selected institute does not exist")
                return redirect("admin:appAuthentication_candidate_changelist")

        if request.method == "POST":
            csv_file = request.FILES.get("csv_file")
            # Get institute_id from POST data
            institute_id = request.POST.get("institute_id")

            if not csv_file:
                messages.error(request, "Please select a CSV file.")
                return redirect(request.get_full_path())

            if not csv_file.name.endswith(".csv"):
                messages.error(request, "Please upload a CSV file.")
                return redirect(request.get_full_path())

            if not institute_id:
                messages.error(request, "Please select an institute.")
                return redirect(request.get_full_path())

            try:
                # Save the file temporarily
                file_name = f"candidate_imports/{institute_id}_{csv_file.name}"
                file_path = default_storage.save(
                    file_name,
                    ContentFile(csv_file.read()),
                )

                # Start the Celery task
                task = process_candidates_csv.delay(file_path, institute_id)

                messages.success(
                    request,
                    f"CSV upload started! Task ID: {task.id}. "
                    "Processing will happen in the background. "
                    "You'll be notified when it's complete.",
                )

                return redirect("admin:appAuthentication_candidate_changelist")

            except Exception as e:
                messages.error(request, f"Error processing file: {e!s}")
                return redirect(request.get_full_path())

        # GET request - show the upload form with preselected institute
        institutes = Institute.objects.all()
        context = {
            "institutes": institutes,
            "institute_id": institute_id,
            "selected_institute": selected_institute,
            "title": "Import Candidates CSV",
            "opts": self.model._meta,
            "has_view_permission": True,
        }
        return render(request, "admin/import_candidates_csv.html", context)
