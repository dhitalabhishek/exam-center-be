from datetime import datetime
from datetime import timedelta

from django.contrib import admin
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe

from appCore.tasks import pause_exam_session
from appCore.tasks import resume_exam_session
from appExam.admin_mixins import ExamSessionActionMixin
from appExam.admin_mixins import ExamSessionBulkActionMixin
from appExam.admin_mixins import ExamSessionDisplayMixin

from .admin_view import download_results_csv_view
from .admin_view import enroll_students_view
from .forms import DocumentUploadForm
from .forms import ExamSessionForm
from .models import Answer
from .models import Exam
from .models import ExamSession
from .models import Hall
from .models import Question
from .models import SeatAssignment
from .models import StudentAnswer
from .models import StudentExamEnrollment
from .question_admin_view import import_questions_document_view
from .question_admin_view import import_questions_view
from .question_admin_view import parse_questions_view
from .utils.export_student_details_pdf import download_exam_excel_view
from .utils.export_student_details_pdf import download_exam_pdf_view

admin.site.register(StudentAnswer)


admin.site.register(SeatAssignment)


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity", "location")
    list_per_page = 10


import logging  # noqa: E402

logger = logging.getLogger(__name__)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_filter = ("program",)
    list_per_page = 10

    def get_list_display(self, request):
        return ["id", "program", "total_marks"]


# Inline for enrollments within ExamSession detail
class EnrollmentInline(admin.TabularInline):
    model = StudentExamEnrollment
    fk_name = "session"
    readonly_fields = ("candidate", "present", "effective_time_remaining")
    fields = ("candidate", "present", "effective_time_remaining")
    extra = 0
    can_delete = False


class QuestionInline(admin.TabularInline):
    model = Question
    fk_name = "session"
    fields = ("text",)
    readonly_fields = ("text",)
    extra = 0
    can_delete = False


# Custom filter: Sessions ending within next X minutes
class TimeLeftFilter(admin.SimpleListFilter):
    title = "Time Left"
    parameter_name = "time_left"

    def lookups(self, request, model_admin):
        return (
            ("<30", "Less than 30 min"),
            ("<60", "Less than 60 min"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == "<30":
            return queryset.filter(expected_end__lte=now + timedelta(minutes=30))
        if self.value() == "<60":
            return queryset.filter(expected_end__lte=now + timedelta(minutes=60))
        return queryset


class BaseStartDateTimeFilter(admin.SimpleListFilter):
    title = "Base Start"
    parameter_name = "filter_base_start"

    def lookups(self, request, model_admin):
        return []

    def queryset(self, request, queryset):
        date = request.GET.get("base_start__date")
        time_str = request.GET.get("base_start__time")

        if date and time_str:
            try:
                # Parse as local timezone
                dt_str = f"{date} {time_str}"
                local_dt = timezone.make_aware(
                    datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S"),  # noqa: DTZ007
                )
                # Convert to UTC for DB querying
                dt_utc = local_dt.astimezone(timezone.utc)
                return queryset.filter(base_start=dt_utc)
            except Exception:  # noqa: BLE001
                return queryset

        elif date:
            try:
                local_date = datetime.strptime(date, "%Y-%m-%d")  # noqa: DTZ007
                local_dt = timezone.make_aware(local_date)
                utc_date = local_dt.astimezone(timezone.utc).date()
                return queryset.filter(base_start__date=utc_date)
            except Exception:  # noqa: BLE001
                return queryset

        return queryset


@admin.register(ExamSession)
class ExamSessionAdmin(
    ExamSessionActionMixin,
    ExamSessionDisplayMixin,
    ExamSessionBulkActionMixin,
    admin.ModelAdmin,
):
    form = ExamSessionForm
    change_list_template = "admin/exam_session_changelist.html"
    search_fields = ("id", "exam_program")
    ordering = ("-base_start",)
    list_display = (
        "id",
        "exam",
        "base_start_display",
        "base_duration",
        "question_count",
        "enrollment_count",
        "status_colored",
        "expected_end",
        "pause_resume_button",
        "actions_column",
    )
    list_filter = ("status", "exam__program", TimeLeftFilter, BaseStartDateTimeFilter)
    date_hierarchy = "base_start"
    list_display_links = ("id", "exam")
    list_per_page = 20
    actions = ["bulk_pause", "bulk_resume", "bulk_end", "enroll_students_action"]
    inlines = [EnrollmentInline, QuestionInline]
    readonly_fields = (
        "effective_start",
        "expected_end",
        "pause_start",
        "total_paused",
        "completed_at",
        "updated_at",
        "created_at",
        "actions_column",
        "session_controls",
    )
    fields = (
        "exam",
        "base_start",
        "base_duration",
        "status",
        "effective_start",
        "expected_end",
        "pause_start",
        "total_paused",
        "completed_at",
        "actions_column",
        "notice",
        "session_controls",
        "updated_at",
        "created_at",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            question_count=Count("question", distinct=True),
            enrollment_count=Count("enrollments", distinct=True),
        )

    def question_count(self, obj):
        return obj.question_count

    question_count.short_description = "Questions"

    def enrollment_count(self, obj):
        return obj.enrollment_count

    enrollment_count.short_description = "Enrollments"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["upload_form"] = DocumentUploadForm()
        extra_context["base_start_filters"] = self.get_base_start_filters(request)
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        """Add custom URLs for session management"""
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:session_id>/download-enrollment/",
                self.admin_site.admin_view(download_exam_excel_view),
                name="exam_session_download_excel",
            ),
            path(
                "<int:session_id>/download-results-csv/",
                self.admin_site.admin_view(download_results_csv_view),
                name="exam_session_download_results_csv",
            ),
            path(
                "<int:session_id>/download-enrollments-pdf/",
                self.admin_site.admin_view(download_exam_pdf_view),
                name="exam_session_download_pdf",
            ),
            path(
                "<int:session_id>/enroll-students/",
                self.admin_site.admin_view(enroll_students_view),
                name="enroll_students",
            ),
            path(
                "<path:object_id>/pause/",
                self.admin_site.admin_view(self.pause_session),
                name="exam_session_pause",
            ),
            path(
                "<path:object_id>/resume/",
                self.admin_site.admin_view(self.resume_session),
                name="exam_session_resume",
            ),
        ]
        return custom_urls + urls

    def actions_column(self, obj):
        """Display actions dropdown - now using the mixin"""
        standalone, dropdown = self.get_session_actions(obj)
        return self.render_dropdown_actions(standalone, dropdown)

    actions_column.short_description = "Actions"

    def session_controls(self, obj):
        """Session controls field for detail view"""
        return self.pause_resume_button(obj)

    session_controls.short_description = "Controls"

    # Session control methods
    def pause_session(self, request, object_id):
        """Pause a specific session"""
        session = get_object_or_404(ExamSession, pk=object_id)
        pause_exam_session.delay(session.id)
        self.message_user(request, f"Exam session '{session}' pause initiated")
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "../"))

    def resume_session(self, request, object_id):
        """Resume a specific session"""
        session = get_object_or_404(ExamSession, pk=object_id)
        resume_exam_session.delay(session.id)
        self.message_user(request, f"Exam session '{session}' resume initiated")
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "../"))


# Filter for disconnected students
class DisconnectedFilter(admin.SimpleListFilter):
    title = "Disconnected"
    parameter_name = "disconnected"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Disconnected"),
            ("no", "Connected"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(present=False)
        if self.value() == "no":
            return queryset.filter(present=True)
        return queryset


@admin.register(StudentExamEnrollment)
class StudentExamEnrollmentAdmin(admin.ModelAdmin):
    search_fields = (
        "candidate__symbol_number",
        "candidate__first_name",
        "candidate__middle_name",
        "candidate__last_name",
        "session__id",
    )
    ordering = ("-connection_start",)
    list_display = (
        "candidate",
        "session",
        "status",
        "present",
        "effective_time_remaining_display",
    )
    list_filter = (
        "session__status",
        "session__exam__program",
        DisconnectedFilter,
    )
    list_per_page = 30
    actions = ["force_submit", "grant_extra_time"]

    readonly_fields = (
        "candidate",
        "session",
        "connection_start",
        "disconnected_at",
        "present",
        "updated_at",
        "created_at",
        "session_started_at",
        "paused_at",
        "paused_duration",
        "individual_paused_at",
        "individual_paused_duration",
    )

    fields = (
        "candidate",
        "session",
        "status",
        "present",
        "session_started_at",
        "individual_duration",
        "connection_start",
        "disconnected_at",
        "paused_at",
        "paused_duration",
        "individual_paused_at",
        "individual_paused_duration",
        "question_order",
        "answer_order",
        "updated_at",
        "created_at",
    )

    def effective_time_remaining_display(self, obj):
        return obj.effective_time_remaining

    effective_time_remaining_display.short_description = "Time Remaining"

    def has_add_permission(self, request):
        return False

    def force_submit(self, request, queryset):
        count = 0
        for enroll in queryset.filter(status="active"):
            if enroll.submit_exam():
                count += 1
        self.message_user(request, f"Forcibly submitted {count} students")

    force_submit.short_description = "Force submit selected students"

    def grant_extra_time(self, request, queryset):
        count = 0
        for enroll in queryset:
            if enroll.individual_paused_duration.total_seconds() > 0:
                enroll.grant_extra_time()
                count += 1
        self.message_user(request, f"Granted extra time to {count} students.")

    grant_extra_time.short_description = "Grant paused time to selected students"


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ("text", "question", "is_correct")
    list_per_page = 10


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "session")
    list_per_page = 10

    def all_answers(self, obj):
        answers = obj.answers.all()
        formatted = []
        for ans in answers:
            url = reverse("admin:appExam_answer_change", args=[ans.id])
            text = escape(ans.text)
            if ans.is_correct:
                formatted.append(
                    f"<a href='{url}' style='color: green; font-weight: bold;'>{text}</a>",  # noqa: E501
                )
            else:
                formatted.append(f"<a href='{url}'>{text}</a>")
        return mark_safe("<br>".join(formatted))  # noqa: S308

    all_answers.short_description = "Answers"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-questions/",
                self.admin_site.admin_view(self.import_questions_view),
                name="appExam_question_import",
            ),
            path(
                "import-questions/<int:session_id>/",
                self.admin_site.admin_view(self.import_questions_document_view),
                name="appExam_question_import_document",
            ),
            path(
                "parse-questions/",
                self.admin_site.admin_view(self.parse_questions_view),
                name="appExam_question_parse",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["import_questions_url"] = reverse("admin:appExam_question_import")
        return super().changelist_view(request, extra_context=extra_context)

    import_questions_view = import_questions_view
    import_questions_document_view = import_questions_document_view
    parse_questions_view = parse_questions_view
