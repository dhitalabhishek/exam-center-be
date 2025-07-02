# admin.py
import csv
from datetime import datetime

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path
from django.urls import reverse

from appAuthentication.models import Candidate
from appExam.models import Question
from appExam.models import StudentExamEnrollment


class CandidateExportAdmin:
    """
    Standalone admin view for exporting all candidate exam data to CSV
    Not tied to any specific model
    """

    def get_urls(self):
        """Define custom URLs for export functionality"""
        return [
            path(
                "candidate-export/",
                self.export_view,
                name="candidate_export_view",
            ),
            path(
                "candidate-export/download/",
                self.download_csv,
                name="candidate_export_download",
            ),
        ]

    def export_view(self, request):
        """Display export options and statistics"""
        context = {
            "title": "Export Candidate Data",
            "total_candidates": Candidate.objects.count(),
            "total_enrollments": StudentExamEnrollment.objects.count(),
            "verified_candidates": Candidate.objects.filter(
                verification_status="verified",
            ).count(),
            "export_url": reverse("admin:candidate_export_download"),
        }
        return render(request, "admin/candidate_export.html", context)

    def download_csv(self, request):
        """Generate and download comprehensive CSV of all candidates"""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="all_candidates_complete_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        )

        writer = csv.writer(response)

        # Write headers
        headers = self.get_csv_headers()
        writer.writerow(headers)

        # Get all candidates and their data
        candidates = Candidate.objects.all().select_related("institute")

        for candidate in candidates:
            rows = self.get_candidate_csv_data(candidate)
            for row in rows:
                writer.writerow(row)

        return response

    def get_csv_headers(self):
        """Define comprehensive CSV headers"""
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
            # Question Details
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
            StudentExamEnrollment.objects.filter(candidate=candidate)
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
            row.extend([""] * (len(self.get_csv_headers()) - len(row)))
            rows.append(row)
            return rows

        for enrollment in enrollments:
            # Get questions for this session
            questions = (
                Question.objects.filter(session=enrollment.session)
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
            marks_obtained = correct_answers
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

                    # Performance metrics
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
                row.extend([0, 0, 0, 0, 0, 0, "0.00%"])
                row.extend(["", "", "No questions in this exam", "", "", "", ""])
                rows.append(row)

        return rows

    def get_basic_candidate_info(self, candidate):
        """Get basic candidate information"""
        full_name = (
            " ".join(
                filter(
                    None,
                    [candidate.first_name, candidate.middle_name, candidate.last_name],
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
