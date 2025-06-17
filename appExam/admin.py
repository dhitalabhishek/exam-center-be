import tempfile
from datetime import timedelta
from pathlib import Path

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import path
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import escape
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from appCore.tasks import pause_exam_session
from appCore.tasks import resume_exam_session

from .forms import DocumentUploadForm
from .models import Answer
from .models import Exam
from .models import ExamSession
from .models import Hall
from .models import HallAndStudentAssignment
from .models import Question
from .models import StudentAnswer
from .models import StudentExamEnrollment
from .tasks import enroll_students_by_symbol_range

admin.site.register(StudentAnswer)


class EnrollmentRangeForm(forms.Form):
    def __init__(self, session_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hall"] = forms.ModelChoiceField(
            queryset=Hall.objects.all(),
            label="Select Hall",
            help_text="Select the hall for the students to be assigned to.",
        )
        self.fields["range_string"] = forms.CharField(
            label="Symbol Number Range",
            max_length=500,
            widget=forms.TextInput(
                attrs={"placeholder": "e.g. 13-A1-PT - 13-A5-PT, 14-B1-PH"},
            ),
            help_text="Enter comma-separated ranges or individual symbols.",
        )


# Custom admin view for enrolling students
@staff_member_required
@require_http_methods(["GET", "POST"])
def enroll_students_view(request, session_id):
    """Custom admin view for enrolling students by range"""
    try:
        session = ExamSession.objects.get(id=session_id)
    except ExamSession.DoesNotExist:
        messages.error(request, f"Exam session with ID {session_id} not found.")
        return redirect("admin:appExam_examsession_changelist")

    if request.method == "POST":
        form = EnrollmentRangeForm(session_id, request.POST)
        if form.is_valid():
            range_string = form.cleaned_data["range_string"]
            hall = form.cleaned_data["hall"]

            # Get or create hall assignment
            hall_assignment, created = HallAndStudentAssignment.objects.get_or_create(
                session=session,
                hall=hall,
                defaults={"roll_number_range": range_string},
            )

            # If already exists, update range
            if not created:
                hall_assignment.roll_number_range = range_string
                hall_assignment.save()

            # Trigger the Celery task
            task = enroll_students_by_symbol_range.delay(
                session_id=session.id,
                hall_assignment_id=hall_assignment.id,
                range_string=range_string,
            )

            messages.success(
                request,
                f"Enrollment task started for range '{range_string}'. "
                f"Task ID: {task.id}. Check the results in few seconds.",
            )
            return redirect("admin:appExam_examsession_change", session.id)
    else:
        form = EnrollmentRangeForm(session_id)

    context = {
        "form": form,
        "session": session,
        "title": f"Enroll Students for {session}",
        "opts": ExamSession._meta,  # noqa: SLF001
        "has_change_permission": True,
        "current_time": timezone.localtime(timezone.now()),
    }

    return render(request, "admin/enroll_students.html", context)


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity", "location")
    list_per_page = 10


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("id", "program", "subject", "total_marks")
    list_filter = ("program",)
    list_per_page = 10


# Inline for enrollments within ExamSession detail
class EnrollmentInline(admin.TabularInline):
    model = StudentExamEnrollment
    fk_name = "session"
    readonly_fields = ("candidate", "present", "effective_time_remaining")
    fields = ("candidate", "present", "effective_time_remaining")
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


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    search_fields = ("id", "exam_program")
    ordering = ("-base_start",)
    list_display = (
        "id",
        "exam",
        "base_start",
        "base_duration",
        "status_colored",
        "expected_end",
        "pause_resume_button",
    )
    list_filter = ("status", "exam__program", TimeLeftFilter)
    date_hierarchy = "base_start"
    list_per_page = 10
    actions = ["bulk_pause", "bulk_resume", "bulk_end"]
    inlines = [EnrollmentInline]

    readonly_fields = (
        "effective_start",
        "expected_end",
        "pause_start",
        "total_paused",
        "completed_at",
        "updated_at",
        "created_at",
        "enroll_students_link",
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
        "enroll_students_link",
        "notice",
        "session_controls",
        "updated_at",
        "created_at",
    )

    def status_colored(self, obj):
        color_map = {
            "scheduled": "gray",
            "ongoing": "green",
            "paused": "orange",
            "completed": "blue",
            "cancelled": "red",
        }
        color = color_map.get(obj.status, "black")
        return format_html(
            '<span style="color: {}; font-weight:bold">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_colored.short_description = "Status"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
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

    def enroll_students_link(self, obj):
        if obj.pk:
            url = reverse("admin:enroll_students", args=[obj.pk])
            return format_html(
                '<a href="{}" class="button">📝 Enroll Students</a>',
                url,
            )
        return "Save the session first"

    enroll_students_link.short_description = "Quick Actions"

    def pause_session(self, request, object_id):
        session = get_object_or_404(ExamSession, pk=object_id)
        pause_exam_session.delay(session.id)
        self.message_user(request, "Exam session pause initiated")
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "../"))

    def resume_session(self, request, object_id):
        session = get_object_or_404(ExamSession, pk=object_id)
        resume_exam_session.delay(session.id)
        self.message_user(request, "Exam session resume initiated")
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "../"))

    def pause_resume_button(self, obj):
        if obj.status == "ongoing":
            return format_html(
                '<a class="button" href="{}">⏸ Pause</a>',
                reverse("admin:exam_session_pause", args=[obj.id]),
            )
        if obj.status == "paused":
            return format_html(
                '<a class="button" href="{}">▶ Resume</a>',
                reverse("admin:exam_session_resume", args=[obj.id]),
            )
        return format_html('<span class="button disabled">Not Active</span>')

    pause_resume_button.short_description = "Session Control"

    def session_controls(self, obj):
        return self.pause_resume_button(obj)

    session_controls.short_description = "Controls"

    # Bulk actions
    def bulk_pause(self, request, queryset):
        for sess in queryset.filter(status="ongoing"):
            pause_exam_session.delay(sess.id)
        self.message_user(request, "Selected sessions are being paused")

    bulk_pause.short_description = "Pause selected sessions"

    def bulk_resume(self, request, queryset):
        for sess in queryset.filter(status="paused"):
            resume_exam_session.delay(sess.id)
        self.message_user(request, "Selected sessions are being resumed")

    bulk_resume.short_description = "Resume selected sessions"

    def bulk_end(self, request, queryset):
        # End each session immediately via model method
        count = 0
        for sess in queryset.filter(status__in=["ongoing", "paused"]):
            if sess.end_session():
                count += 1
        self.message_user(request, f"Ended {count} selected sessions")

    bulk_end.short_description = "End selected sessions"

    # Custom action for student enrollment
    def enroll_students_action(self, request, queryset):
        """Admin action to enroll students for selected exam sessions"""
        if queryset.count() > 1:
            self.message_user(
                request,
                "Please select only one exam session at a time for enrollment.",
                level=messages.ERROR,
            )
            return None

        session = queryset.first()
        url = reverse("admin:enroll_students", args=[session.pk])
        return HttpResponseRedirect(url)

    enroll_students_action.short_description = "📝 Enroll students by symbol range"


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
    search_fields = ("candidate__symbol_number", "session__id")
    ordering = ("-connection_start",)
    list_display = (
        "candidate",
        "session",
        "status",
        "present",
        "effective_time_remaining_display",
    )
    list_filter = ("session__status", "session__exam__program", DisconnectedFilter)
    list_per_page = 10
    actions = ["force_submit"]

    readonly_fields = (
        "candidate",
        "session",
        "connection_start",
        "disconnected_at",
        "present",
        "updated_at",
        "created_at",
    )
    fields = (
        "candidate",
        "session",
        "status",
        "present",
        "connection_start",
        "disconnected_at",
        "individual_duration",
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
                    f"<a href='{url}' style='color: green; font-weight: bold;'>{text} ✅</a>",  # noqa: E501
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

    def import_questions_view(self, request):
        """View to display list of exam sessions for selection"""
        exam_sessions = ExamSession.objects.all().order_by("-base_start")

        context = {
            **self.admin_site.each_context(request),
            "title": "Select Exam Session",
            "exam_sessions": exam_sessions,
            "opts": self.model._meta,  # noqa: SLF001
            "has_view_permission": True,
            "current_time": timezone.localtime(timezone.now()),
        }

        return TemplateResponse(
            request,
            "admin/appExam/question/select_session.html",
            context,
        )

    def import_questions_document_view(self, request, session_id):  # noqa: C901
        """View to upload document and parse questions"""
        session = get_object_or_404(ExamSession, id=session_id)

        if request.method == "POST":
            form = DocumentUploadForm(request.POST, request.FILES)
            if form.is_valid():
                document = request.FILES["document"]
                file_extension = Path(document.name).suffix.lower()

                # Store document info in session
                request.session["document_name"] = document.name
                request.session["session_id"] = session_id

                try:
                    content = ""

                    if file_extension == ".txt":
                        # Handle .txt files
                        content = document.read().decode("utf-8")
                        request.session["document_content"] = content

                    elif file_extension == ".docx":
                        # Handle .docx files
                        with tempfile.NamedTemporaryFile(
                            delete=False,
                            suffix=".docx",
                        ) as temp_file:
                            for chunk in document.chunks():
                                temp_file.write(chunk)
                            temp_file_path = temp_file.name

                        try:
                            # Parse the .docx file
                            import docx

                            doc = docx.Document(temp_file_path)
                            content = "\n".join(
                                [paragraph.text for paragraph in doc.paragraphs],
                            )

                            # Store the temp file path for later processing
                            request.session["temp_file_path"] = temp_file_path
                            request.session["document_content"] = content

                        except Exception as e:
                            if Path(temp_file_path).exists():
                                Path(temp_file_path).unlink()
                            raise e  # noqa: TRY201

                    else:
                        messages.error(
                            request,
                            "Only .txt and .docx files are supported",
                        )
                        return redirect(
                            "admin:appExam_question_import_document",
                            session_id=session_id,
                        )

                    # Validate the document format
                    from .utils.questionParser import validate_question_format

                    validation_result = validate_question_format(content)

                    if not validation_result["is_valid"]:
                        messages.warning(
                            request,
                            f"Document format validation: {validation_result['message']}",  # noqa: E501
                        )

                    context = {
                        **self.admin_site.each_context(request),
                        "title": f"Import Questions - {session}",
                        "session": session,
                        "document_name": document.name,
                        "document_content": content,
                        "validation_result": validation_result,
                        "opts": self.model._meta,  # noqa: SLF001
                        "has_view_permission": True,
                        "current_time": timezone.localtime(timezone.now()),
                    }

                    return TemplateResponse(
                        request,
                        "admin/appExam/question/parse_document.html",
                        context,
                    )

                except Exception as e:  # noqa: BLE001
                    messages.error(request, f"Error reading document: {e!s}")
                    # Clean up any temp files
                    if temp_file_path and Path(temp_file_path).exists():
                        Path(temp_file_path).unlink()
                        request.session.pop("temp_file_path", None)
                        request.session.pop("temp_file_path", None)
        else:
            form = DocumentUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "title": f"Upload Document - {session}",
            "form": form,
            "session": session,
            "supported_formats": [".txt", ".docx"],
            "opts": self.model._meta,  # noqa: SLF001
            "has_view_permission": True,
            "current_time": timezone.localtime(timezone.now()),
        }

        return TemplateResponse(
            request,
            "admin/appExam/question/upload_document.html",
            context,
        )

    @method_decorator(csrf_exempt)
    def parse_questions_view(self, request):
        """AJAX view to parse questions from document"""
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)

        try:
            session_id = request.session.get("session_id")
            document_content = request.session.get("document_content")
            temp_file_path = request.session.get("temp_file_path")

            if not session_id or not document_content:
                return JsonResponse(
                    {"error": "Session expired. Please start over."},
                    status=400,
                )

            session = get_object_or_404(ExamSession, id=session_id)

            # Parse questions from document
            if temp_file_path and Path(temp_file_path).exists():
                # For .docx files, use the temp file
                from .utils.questionParser import parse_questions_from_docx

                parsed_data = parse_questions_from_docx(temp_file_path)

                # Clean up temp file
                Path(temp_file_path).unlink()
                request.session.pop("temp_file_path", None)
            else:
                # For .txt files, use the content
                from .utils.questionParser import parse_questions_from_document

                parsed_data = parse_questions_from_document(document_content)

            # Create questions and answers
            created_count = 0
            for question_data in parsed_data:
                question = Question.objects.create(
                    text=question_data["question"],
                    session=session,
                )

                for answer_data in question_data["answers"]:
                    Answer.objects.create(
                        question=question,
                        text=answer_data["text"],
                        is_correct=answer_data["is_correct"],
                    )

                created_count += 1

            # Clear session data
            request.session.pop("document_content", None)
            request.session.pop("document_name", None)
            request.session.pop("session_id", None)

            return JsonResponse(
                {
                    "success": True,
                    "message": f"Successfully imported {created_count} questions with answers.",  # noqa: E501
                    "redirect_url": reverse("admin:appExam_question_changelist"),
                },
            )

        except (OSError, ValueError) as e:
            # Clean up any remaining temp files
            temp_file_path = request.session.get("temp_file_path")
            if temp_file_path and Path(temp_file_path).exists():
                Path(temp_file_path).unlink()
                request.session.pop("temp_file_path", None)

            return JsonResponse({"error": str(e)}, status=500)
