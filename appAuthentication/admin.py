from django.contrib import admin
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import path

from appInstitutions.models import Institute

from .models import Candidate
from .models import User
from .tasks import process_candidates_file
from .tasks import validate_file_format


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
    list_display = ("symbol_number", "first_name", "last_name", "get_institute_name", "program_id")
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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-candidates/",
                self.admin_site.admin_view(self.import_candidates),
                name="appAuthentication_candidate_import",
            ),
        ]
        return custom_urls + urls

    def import_candidates(self, request):
        """
        Import candidates from CSV or Excel files
        """
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
            uploaded_file = request.FILES.get("candidate_file")
            # Get institute_id from POST data
            institute_id = request.POST.get("institute_id")

            # Validation
            if not uploaded_file:
                messages.error(request, "Please select a file.")
                return redirect(request.get_full_path())

            # Check file extension
            allowed_extensions = [".csv", ".xlsx", ".xls"]
            file_extension = uploaded_file.name.lower().split(".")[-1]
            if f".{file_extension}" not in allowed_extensions:
                messages.error(request, "Please upload a CSV or Excel file (.csv, .xlsx, .xls).")
                return redirect(request.get_full_path())

            if not institute_id:
                messages.error(request, "Please select an institute.")
                return redirect(request.get_full_path())

            try:
                # Save the file temporarily
                file_name = f"candidate_imports/{institute_id}_{uploaded_file.name}"
                file_path = default_storage.save(
                    file_name,
                    ContentFile(uploaded_file.read()),
                )

                # Validate file format before processing
                validation_result = validate_file_format(file_path)

                if not validation_result["is_valid"]:
                    # Clean up the uploaded file
                    default_storage.delete(file_path)
                    messages.error(request, f"File validation failed: {validation_result['error']}")
                    return redirect(request.get_full_path())

                # Start the Celery task with the new function
                task = process_candidates_file.delay(file_path, institute_id)

                messages.success(
                    request,
                    f"File upload started! Task ID: {task.id}. "
                    f"Processing {validation_result['total_rows']} rows from {validation_result['file_type']} file. "
                    "Processing will happen in the background. "
                    "You'll be notified when it's complete.",
                )
                return redirect("admin:appAuthentication_candidate_changelist")

            except Exception as e:
                # Clean up file if it was saved
                if "file_path" in locals():
                    try:  # noqa: SIM105
                        default_storage.delete(file_path)
                    except:  # noqa: E722, S110
                        pass
                messages.error(request, f"Error processing file: {e!s}")
                return redirect(request.get_full_path())

        # GET request - show the upload form with preselected institute
        institutes = Institute.objects.all()
        context = {
            "institutes": institutes,
            "institute_id": institute_id,
            "selected_institute": selected_institute,
            "title": "Import Candidates",
            "opts": self.model._meta,  # noqa: SLF001
            "has_view_permission": True,
            "allowed_formats": "CSV, Excel (.xlsx, .xls)",
        }
        return render(request, "admin/import_candidates.html", context)
