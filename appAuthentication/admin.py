from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import path
from django.utils.translation import gettext_lazy as _

from appInstitutions.models import Institute

from .forms import DualPasswordAuthenticationForm
from .models import Candidate
from .models import User
from .tasks import process_candidates_file
from .tasks import validate_file_format

admin.site.login_form = DualPasswordAuthenticationForm


class AdminUserChangeForm(forms.ModelForm):
    old_admin_password2 = forms.CharField(
        label=_("Old Second Password"),
        widget=forms.PasswordInput,
        required=False,
        help_text=_("Required to change the second password."),
    )
    new_admin_password2 = forms.CharField(
        label=_("New Second Password"),
        widget=forms.PasswordInput,
        required=False,
        help_text=_("Enter a new second password. Leave blank to keep current one."),
    )

    class Meta:
        model = User
        fields = ("email", "is_staff", "is_superuser", "is_admin", "admin_password2")

    def clean(self):
        cleaned_data = super().clean()
        user = self.instance
        old_pass = cleaned_data.get("old_admin_password2")
        new_pass = cleaned_data.get("new_admin_password2")

        if user.admin_password2:
            # If second password is already set, old must be provided and correct
            if new_pass and not old_pass:
                msg = "Old second password is required to set a new one."
                raise forms.ValidationError(msg)
            if new_pass and old_pass and not user.check_admin_password2(old_pass):
                msg = "Old second password is incorrect."
                raise forms.ValidationError(msg)
        return cleaned_data

    def save(self, commit=True):  # noqa: FBT002
        user = super().save(commit=False)
        new_pass = self.cleaned_data.get("new_admin_password2")
        if new_pass:
            user.set_admin_password2(new_pass)
        if commit:
            user.save()
        return user


@admin.register(User)
class CustomUserAdmin(admin.ModelAdmin):
    form = AdminUserChangeForm
    list_display = ("email", "last_login", "is_superuser")
    ordering = ("-is_superuser", "email")  # superusers at top
    search_fields = ("email",)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = ["admin_password2"]
        if obj:
            readonly_fields += ["password"]
        return readonly_fields


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    readonly_fields = ("verification_status", "user")
    list_display = (
        "symbol_number",
        "first_name",
        "last_name",
        "get_institute_name",
        "program_id",
        "level_id",
        "exam_status",
    )
    search_fields = ("symbol_number", "first_name", "last_name", "email", "phone")
    list_filter = (
        "institute",
        "exam_status",
        "program_id",
        "level_id",
    )

    def get_institute_name(self, obj):
        return obj.institute.name if obj.institute else "No Institute"

    get_institute_name.short_description = "Institute"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_import_button"] = True
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

    def import_candidates(self, request):  # noqa: C901, PLR0911
        institute_id = request.GET.get("institute_id")
        selected_institute = None

        if institute_id:
            try:
                selected_institute = Institute.objects.get(id=institute_id)
            except Institute.DoesNotExist:
                messages.error(request, "Selected institute does not exist")
                return redirect("admin:appAuthentication_candidate_changelist")

        if request.method == "POST":
            uploaded_file = request.FILES.get("candidate_file")
            institute_id = request.POST.get("institute_id")
            file_format = request.POST.get("file_format", "auto")

            if not uploaded_file:
                messages.error(request, "Please select a file.")
                return redirect(request.get_full_path())

            allowed_extensions = [".csv", ".xlsx", ".xls"]
            file_extension = uploaded_file.name.lower().split(".")[-1]
            if f".{file_extension}" not in allowed_extensions:
                messages.error(
                    request,
                    "Please upload a CSV or Excel file (.csv, .xlsx, .xls).",
                )
                return redirect(request.get_full_path())

            if not institute_id:
                messages.error(request, "Please select an institute.")
                return redirect(request.get_full_path())

            try:
                file_name = f"candidate_imports/{institute_id}_{uploaded_file.name}"
                file_path = default_storage.save(
                    file_name,
                    ContentFile(uploaded_file.read()),
                )

                expected_format = None if file_format == "auto" else file_format
                validation_result = validate_file_format(file_path, expected_format)

                if not validation_result["is_valid"]:
                    default_storage.delete(file_path)
                    messages.error(
                        request,
                        f"File validation failed: {validation_result['error']}",
                    )
                    return redirect(request.get_full_path())

                final_format = validation_result.get("detected_format", "format1")

                task = process_candidates_file.delay(
                    file_path,
                    institute_id,
                    final_format,
                )

                messages.success(
                    request,
                    f"File upload started! Task ID: {task.id}. "
                    f"Processing {validation_result['total_rows']} rows from {validation_result['file_type']} file "
                    f"using {final_format}. "
                    "You'll be notified when it's complete.",
                )
                return redirect("admin:appAuthentication_candidate_changelist")

            except Exception as e:
                if "file_path" in locals():
                    try:
                        default_storage.delete(file_path)
                    except:
                        pass
                messages.error(request, f"Error processing file: {e!s}")
                return redirect(request.get_full_path())

        institutes = Institute.objects.all()
        context = {
            "institutes": institutes,
            "institute_id": institute_id,
            "selected_institute": selected_institute,
            "title": "Import Candidates",
            "opts": self.model._meta,
            "has_view_permission": True,
            "allowed_formats": "CSV, Excel (.xlsx, .xls)",
        }
        return render(request, "admin/import_candidates.html", context)
