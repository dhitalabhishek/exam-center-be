# admin.py
import csv
from datetime import datetime

from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import path
from django.urls import reverse
from django.utils.html import format_html

from appAuthentication.models import Candidate
from appExam.models import Question
from appExam.models import StudentAnswer
from appExam.models import StudentExamEnrollment


class CandidateExamCSVAdmin(admin.ModelAdmin):
    """
    Admin interface for exporting comprehensive candidate exam data to CSV
    """

    model = Candidate

    # Display fields in the list view
    list_display = [
        "symbol_number",
        "full_name_display",
        "institute",
        "verification_status",
        "exam_status",
        "total_exams_taken",
        "export_csv_link",
    ]

    # Filters
    list_filter = [
        "verification_status",
        "exam_status",
        "institute",
        (
            "user__studentexamenrollment__session__exam__program",
            admin.RelatedOnlyFieldListFilter,
        ),
        (
            "user__studentexamenrollment__session__exam__subject",
            admin.RelatedOnlyFieldListFilter,
        ),
    ]

    # Search functionality
    search_fields = [
        "symbol_number",
        "first_name",
        "last_name",
        "email",
        "phone",
    ]

    # Ordering
    ordering = ["symbol_number"]

    # Add custom actions
    actions = ["export_selected_candidates_csv", "export_all_candidates_csv"]

    def get_urls(self):
        """Add custom URLs for CSV export"""
        urls = super().get_urls()
        custom_urls = [
            path(
                "export-csv/<int:candidate_id>/",
                self.admin_site.admin_view(self.export_single_candidate_csv),
                name="candidate_export_csv",
            ),
            path(
                "export-all-csv/",
                self.admin_site.admin_view(self.export_all_candidates_csv_view),
                name="candidates_export_all_csv",
            ),
        ]
        return custom_urls + urls

    def full_name_display(self, obj):
        """Display full name"""
        parts = [obj.first_name, obj.middle_name, obj.last_name]
        return " ".join(filter(None, parts)) or "Unknown Name"

    full_name_display.short_description = "Full Name"

    def total_exams_taken(self, obj):
        """Count total exams taken by candidate"""
        return StudentExamEnrollment.objects.filter(candidate=obj).count()

    total_exams_taken.short_description = "Exams Taken"

    def export_csv_link(self, obj):
        """Link to export individual candidate CSV"""
        url = reverse("admin:candidate_export_csv", args=[obj.pk])
        return format_html('<a href="{}" class="button">Export CSV</a>', url)

    export_csv_link.short_description = "Export"

    def export_selected_candidates_csv(self, request, queryset):
        """Action to export selected candidates to CSV"""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="candidates_exam_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        )

        writer = csv.writer(response)

        # Write headers
        headers = self.get_csv_headers()
        writer.writerow(headers)

        # Write data for each candidate
        for candidate in queryset:
            rows = self.get_candidate_csv_data(candidate)
            for row in rows:
                writer.writerow(row)

        self.message_user(
            request, f"Successfully exported {queryset.count()} candidates to CSV.",
        )
        return response

    export_selected_candidates_csv.short_description = (
        "Export selected candidates to CSV"
    )

    def export_all_candidates_csv(self, request, queryset):
        """Action to export all candidates to CSV"""
        all_candidates = Candidate.objects.all()
        return self.export_selected_candidates_csv(request, all_candidates)

    export_all_candidates_csv.short_description = "Export ALL candidates to CSV"

    def export_single_candidate_csv(self, request, candidate_id):
        """Export single candidate data to CSV"""
        try:
            candidate = Candidate.objects.get(pk=candidate_id)
        except Candidate.DoesNotExist:
            messages.error(request, "Candidate not found.")
            return redirect("admin:appAuthentication_candidate_changelist")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="candidate_{candidate.symbol_number}_exam_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        )

        writer = csv.writer(response)

        # Write headers
        headers = self.get_csv_headers()
        writer.writerow(headers)

        # Write candidate data
        rows = self.get_candidate_csv_data(candidate)
        for row in rows:
            writer.writerow(row)

        return response

    def export_all_candidates_csv_view(self, request):
        """View to export all candidates data to CSV"""
        all_candidates = Candidate.objects.all()

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="all_candidates_exam_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        )

        writer = csv.writer(response)

        # Write headers
        headers = self.get_csv_headers()
        writer.writerow(headers)

        # Write data for each candidate
        for candidate in all_candidates:
            rows = self.get_candidate_csv_data(candidate)
            for row in rows:
                writer.writerow(row)

        return response

    def get_csv_headers(self):
        """Define CSV headers"""
        return [
            # Candidate Basic Info
            "Symbol Number",
            "First Name",
            "Middle Name",
            "Last Name",
            "Full Name",
            "Email",
            "Phone",
            "Institute",
            "Verification Status",
            "Exam Status",
            "Gender",
            "Citizenship No",
            "Date of Birth (Nepali)",
            "Level",
            "Program",
            # Exam Session Info
            "Exam Name",
            "Exam Program",
            "Exam Subject",
            "Exam Date",
            "Exam Duration",
            "Total Marks Available",
            "Hall Name",
            "Hall Location",
            "Seat Number",
            # Enrollment Status
            "Enrollment Status",
            "Session Started At",
            "Connection Start Time",
            "Last Disconnection Time",
            "Present Status",
            "Paused Duration",
            "Individual Paused Duration",
            "Time Remaining",
            # Performance Metrics
            "Total Questions",
            "Attempted Questions",
            "Correct Answers",
            "Incorrect Answers",
            "Unattempted Questions",
            "Marks Obtained",
            "Percentage",
            # Question Details (Dynamic - will be filled for each question)
            "Question Order",
            "Question Number",
            "Question Text",
            "Student Answer",
            "Correct Answer",
            "Is Student Answer Correct",
            "Question Mark",
        ]

    def get_candidate_csv_data(self, candidate):
        """Get comprehensive CSV data for a candidate"""
        rows = []

        # Get all enrollments for this candidate
        enrollments = (
            StudentExamEnrollment.objects.filter(
                candidate=candidate,
            )
            .select_related(
                "session__exam__program",
                "session__exam__subject",
                "hall_assignment__hall",
            )
            .prefetch_related(
                "student_answers__question",
                "student_answers__selected_answer",
                "session__question_set__answers",
            )
        )

        if not enrollments.exists():
            # If no enrollments, create a row with basic candidate info
            row = self.get_basic_candidate_info(candidate)
            row.extend(
                [""] * (len(self.get_csv_headers()) - len(row)),
            )  # Fill remaining columns
            rows.append(row)
            return rows

        for enrollment in enrollments:
            # Get questions for this session
            questions = (
                Question.objects.filter(
                    session=enrollment.session,
                )
                .prefetch_related("answers")
                .order_by("id")
            )

            # Get student answers
            student_answers = {
                sa.question_id: sa for sa in enrollment.student_answers.all()
            }

            # Calculate performance metrics
            total_questions = questions.count()
            attempted_questions = sum(
                1 for sa in student_answers.values() if sa.selected_answer is not None
            )
            correct_answers = sum(
                1
                for sa in student_answers.values()
                if sa.selected_answer and sa.selected_answer.is_correct
            )
            incorrect_answers = attempted_questions - correct_answers
            unattempted_questions = total_questions - attempted_questions
            marks_obtained = correct_answers  # Assuming 1 mark per correct answer
            total_marks = enrollment.session.exam.total_marks
            percentage = (marks_obtained / total_marks * 100) if total_marks > 0 else 0

            if questions.exists():
                # Create a row for each question
                for i, question in enumerate(questions, 1):
                    row = []

                    # Basic candidate info
                    row.extend(self.get_basic_candidate_info(candidate))

                    # Exam session info
                    row.extend(self.get_exam_session_info(enrollment))

                    # Performance metrics (same for all questions of this exam)
                    row.extend(
                        [
                            total_questions,
                            attempted_questions,
                            correct_answers,
                            incorrect_answers,
                            unattempted_questions,
                            marks_obtained,
                            f"{percentage:.2f}%",
                        ],
                    )

                    # Question-specific info
                    student_answer = student_answers.get(question.id)
                    correct_answer = question.answers.filter(is_correct=True).first()

                    question_order = enrollment.question_order
                    question_position = (
                        question_order.index(question.id) + 1
                        if question.id in question_order
                        else i
                    )

                    if student_answer and student_answer.selected_answer:
                        student_answer_text = student_answer.selected_answer.text
                        is_correct = student_answer.selected_answer.is_correct
                        question_mark = 1 if is_correct else 0
                    else:
                        student_answer_text = "Not Answered"
                        is_correct = False
                        question_mark = 0

                    row.extend(
                        [
                            str(question_order) if question_order else "",
                            question_position,
                            question.text,
                            student_answer_text,
                            correct_answer.text
                            if correct_answer
                            else "No correct answer set",
                            "Yes" if is_correct else "No",
                            question_mark,
                        ],
                    )

                    rows.append(row)
            else:
                # No questions, but enrollment exists
                row = []
                row.extend(self.get_basic_candidate_info(candidate))
                row.extend(self.get_exam_session_info(enrollment))
                row.extend(
                    [
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        "0.00%",  # Performance metrics
                    ],
                )
                row.extend(
                    ["", "", "No questions in this exam", "", "", "", ""],
                )  # Question info
                rows.append(row)

        return rows

    def get_basic_candidate_info(self, candidate):
        """Get basic candidate information"""
        full_name = (
            " ".join(
                filter(
                    None,
                    [
                        candidate.first_name,
                        candidate.middle_name,
                        candidate.last_name,
                    ],
                ),
            )
            or "Unknown Name"
        )

        return [
            candidate.symbol_number,
            candidate.first_name,
            candidate.middle_name or "",
            candidate.last_name or "",
            full_name,
            candidate.email,
            candidate.phone,
            candidate.institute.name if candidate.institute else "",
            candidate.get_verification_status_display(),
            candidate.get_exam_status_display(),
            candidate.gender or "",
            candidate.citizenship_no or "",
            candidate.dob_nep,
            candidate.level,
            candidate.program,
        ]

    def get_exam_session_info(self, enrollment):
        """Get exam session information"""
        session = enrollment.session
        exam = session.exam

        exam_name = f"{exam.program.name}"
        if exam.subject:
            exam_name += f" - {exam.subject.name}"

        hall_info = enrollment.hall_assignment
        seat_info = getattr(enrollment, "seat_assignment", None)

        return [
            exam_name,
            exam.program.name,
            exam.subject.name if exam.subject else "",
            session.base_start.strftime("%Y-%m-%d %H:%M:%S"),
            str(enrollment.individual_duration),
            exam.total_marks,
            hall_info.hall.name if hall_info else "",
            hall_info.hall.location if hall_info else "",
            seat_info.seat_number if seat_info else "",
            # Enrollment status info
            enrollment.get_status_display(),
            enrollment.session_started_at.strftime("%Y-%m-%d %H:%M:%S")
            if enrollment.session_started_at
            else "",
            enrollment.connection_start.strftime("%Y-%m-%d %H:%M:%S")
            if enrollment.connection_start
            else "",
            enrollment.disconnected_at.strftime("%Y-%m-%d %H:%M:%S")
            if enrollment.disconnected_at
            else "",
            "Present" if enrollment.present else "Absent",
            str(enrollment.paused_duration),
            str(enrollment.individual_paused_duration),
            str(enrollment.effective_time_remaining),
        ]

    def changelist_view(self, request, extra_context=None):
        """Add export all button to changelist"""
        extra_context = extra_context or {}
        extra_context["export_all_url"] = reverse("admin:candidates_export_all_csv")
        return super().changelist_view(request, extra_context)


# Register the admin
admin.site.register(Candidate, CandidateExamCSVAdmin)


# Optional: Create a separate admin action for bulk operations
class ExamDataExportAdmin(admin.ModelAdmin):
    """
    Dedicated admin for exam data export operations
    """

    model = StudentExamEnrollment

    list_display = [
        "candidate_symbol_number",
        "candidate_name",
        "exam_name",
        "session_date",
        "status",
        "marks_obtained",
        "percentage",
    ]

    list_filter = [
        "status",
        "session__exam__program",
        "session__exam__subject",
        "session__base_start",
        "candidate__institute",
    ]

    search_fields = [
        "candidate__symbol_number",
        "candidate__first_name",
        "candidate__last_name",
    ]

    actions = ["export_enrollment_data_csv"]

    def candidate_symbol_number(self, obj):
        return obj.candidate.symbol_number

    candidate_symbol_number.short_description = "Symbol Number"

    def candidate_name(self, obj):
        parts = [
            obj.candidate.first_name,
            obj.candidate.middle_name,
            obj.candidate.last_name,
        ]
        return " ".join(filter(None, parts))

    candidate_name.short_description = "Candidate Name"

    def exam_name(self, obj):
        exam_name = obj.session.exam.program.name
        if obj.session.exam.subject:
            exam_name += f" - {obj.session.exam.subject.name}"
        return exam_name

    exam_name.short_description = "Exam"

    def session_date(self, obj):
        return obj.session.base_start.strftime("%Y-%m-%d %H:%M")

    session_date.short_description = "Date"

    def marks_obtained(self, obj):
        correct_answers = StudentAnswer.objects.filter(
            enrollment=obj,
            selected_answer__is_correct=True,
        ).count()
        return correct_answers

    marks_obtained.short_description = "Marks"

    def percentage(self, obj):
        total_marks = obj.session.exam.total_marks or 1
        obtained = self.marks_obtained(obj)
        return f"{(obtained / total_marks * 100):.1f}%"

    percentage.short_description = "Percentage"

    def export_enrollment_data_csv(self, request, queryset):
        """Export enrollment data to CSV"""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="exam_enrollments_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        )

        writer = csv.writer(response)

        # Headers
        writer.writerow(
            [
                "Symbol Number",
                "Candidate Name",
                "Institute",
                "Exam",
                "Date",
                "Status",
                "Total Questions",
                "Attempted",
                "Correct",
                "Incorrect",
                "Marks",
                "Percentage",
                "Duration",
                "Time Remaining",
            ],
        )

        # Data
        for enrollment in queryset:
            total_questions = Question.objects.filter(
                session=enrollment.session,
            ).count()
            student_answers = StudentAnswer.objects.filter(enrollment=enrollment)
            attempted = student_answers.filter(selected_answer__isnull=False).count()
            correct = student_answers.filter(selected_answer__is_correct=True).count()
            incorrect = attempted - correct

            writer.writerow(
                [
                    enrollment.candidate.symbol_number,
                    self.candidate_name(enrollment),
                    enrollment.candidate.institute.name,
                    self.exam_name(enrollment),
                    self.session_date(enrollment),
                    enrollment.get_status_display(),
                    total_questions,
                    attempted,
                    correct,
                    incorrect,
                    correct,  # Assuming 1 mark per correct answer
                    self.percentage(enrollment),
                    str(enrollment.individual_duration),
                    str(enrollment.effective_time_remaining),
                ],
            )

        return response

    export_enrollment_data_csv.short_description = "Export to CSV"


# Register the exam data export admin
admin.site.register(StudentExamEnrollment, ExamDataExportAdmin)
