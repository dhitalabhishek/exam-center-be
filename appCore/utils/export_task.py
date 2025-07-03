import csv
import os
import zipfile
from datetime import datetime
from io import StringIO

from celery import shared_task
from django.conf import settings
from django.db.models import Prefetch

from appCore.utils.track_task import track_task
from appExam.models import ExamSession
from appExam.models import Question
from appExam.models import StudentAnswer
from appExam.models import StudentExamEnrollment


@shared_task(bind=True)
def export_candidates_by_sessions_task(self):
    """
    Celery task to export candidate data session-wise
    Creates separate CSV file for each exam session
    """
    task_id = self.request.id
    task_name = "Export Candidates by Sessions"

    with track_task(task_id, task_name) as task:
        try:
            file_path = export_candidates_by_sessions(task)
            task.message = f"Export completed. ZIP file saved at: {file_path}"
            return {"status": "success", "file_path": file_path}

        except Exception as e:
            task.message = f"Export failed: {e!s}"
            raise


def export_candidates_by_sessions(task):
    """Export candidates data session-wise and create a ZIP file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create a temporary directory for CSV files
    temp_dir = f"temp_exports_{timestamp}"
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # Get all sessions with enrollments
        sessions = (
            ExamSession.objects.filter(enrollments__isnull=False)
            .distinct()
            .select_related("exam__program", "exam__subject")
            .order_by("base_start")
        )

        total_sessions = sessions.count()
        csv_files = []

        task.progress = 10
        task.message = f"Found {total_sessions} sessions with enrollments to process"
        task.save()

        if total_sessions == 0:
            task.message = "No sessions with enrollments found"
            task.save()
            return None

        for i, session in enumerate(sessions):
            # Update progress
            progress = 10 + (i * 80 // total_sessions)
            task.progress = progress

            session_name = f"{session.exam.program.name}"
            if session.exam.subject:
                session_name += f" - {session.exam.subject.name}"

            task.message = (
                f"Processing session {i + 1}/{total_sessions}: {session_name}"
            )
            task.save()

            # Generate CSV for this session
            csv_content = generate_session_csv(session)

            if csv_content:  # Only create file if there's data
                # Create filename
                session_date = session.base_start.strftime("%Y%m%d_%H%M")
                filename = f"{session_name}_{session_date}.csv"

                # Clean filename (remove special characters)
                filename = "".join(
                    c for c in filename if c.isalnum() or c in "._- "
                ).strip()
                filename = filename.replace(" ", "_")

                file_path = os.path.join(temp_dir, filename)

                # Write CSV file
                with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
                    csvfile.write(csv_content)

                csv_files.append(file_path)

        task.progress = 90
        task.message = f"Creating ZIP file with {len(csv_files)} session files"
        task.save()

        # Create ZIP file
        zip_filename = f"candidate_exports_by_session_{timestamp}.zip"
        zip_path = os.path.join(settings.MEDIA_ROOT, "exports", zip_filename)

        # Ensure exports directory exists
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for csv_file in csv_files:
                zipf.write(csv_file, os.path.basename(csv_file))

        task.progress = 100
        task.message = (
            f"ZIP file created successfully with {len(csv_files)} session files"
        )
        task.save()

        return f"exports/{zip_filename}"

    finally:
        # Clean up temporary files
        for csv_file in csv_files:
            if os.path.exists(csv_file):
                os.remove(csv_file)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)


def generate_session_csv(session):
    """Generate CSV content for a specific session"""
    # Get enrollments for this session
    enrollments = (
        StudentExamEnrollment.objects.filter(session=session)
        .select_related(
            "candidate",
            "candidate__institute",
            "seat_assignment__hall",
        )
        .prefetch_related(
            Prefetch(
                "student_answers",
                queryset=StudentAnswer.objects.select_related(
                    "question",
                    "selected_answer",
                ),
            ),
        )
        .order_by("candidate__symbol_number")
    )

    if not enrollments.exists():
        return None  # No data for this session

    # Get questions for this session
    questions = list(
        Question.objects.filter(session=session)
        .prefetch_related("answers")
        .order_by("id"),
    )

    if not questions:
        return None  # No questions for this session

    # Create CSV content
    output = StringIO()
    writer = csv.writer(output)

    # Write headers
    headers = get_session_csv_headers(questions)
    writer.writerow(headers)

    # Write data rows
    for enrollment in enrollments:
        row = get_session_enrollment_row(enrollment, questions)
        writer.writerow(row)

    return output.getvalue()


def get_session_csv_headers(questions):
    """Get headers for session-specific CSV"""
    headers = [
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
    ]

    # Add question texts as column headers
    for i, question in enumerate(questions, 1):
        # Create a shorter question header (first 50 chars + question number)
        question_header = f"Q{i}: {question.text[:50]}..."
        if len(question.text) <= 50:
            question_header = f"Q{i}: {question.text}"
        headers.append(question_header)

    return headers


def get_session_enrollment_row(enrollment, questions):
    """Get CSV row data for a specific enrollment in a session"""
    candidate = enrollment.candidate

    # Start with basic candidate info
    row = get_basic_candidate_info(candidate)

    # Add exam session info
    row.extend(get_exam_session_info(enrollment))

    # Get student answers as a dictionary for quick lookup
    student_answers = {sa.question_id: sa for sa in enrollment.student_answers.all()}

    # Calculate performance metrics
    total_questions = len(questions)
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

    # Add performance metrics
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

    # Add student answers for each question
    for question in questions:
        student_answer = student_answers.get(question.id)
        if student_answer and student_answer.selected_answer:
            answer_text = student_answer.selected_answer.text
        else:
            answer_text = "Not Answered"
        row.append(answer_text)

    return row


def get_basic_candidate_info(candidate):
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
        candidate.symbol_number or "",
        candidate.first_name or "",
        candidate.middle_name or "",
        candidate.last_name or "",
        full_name,
        candidate.email or "",
        candidate.phone or "",
        candidate.institute.name if candidate.institute else "",
        candidate.get_verification_status_display()
        if hasattr(candidate, "get_verification_status_display")
        else "",
        candidate.get_exam_status_display()
        if hasattr(candidate, "get_exam_status_display")
        else "",
        candidate.gender or "",
        candidate.citizenship_no or "",
        candidate.dob_nep or "",
        candidate.level or "",
        candidate.program or "",
    ]


def get_exam_session_info(enrollment):
    """Get exam session information"""
    session = enrollment.session
    exam = session.exam

    exam_name = f"{exam.program.name}"
    if exam.subject:
        exam_name += f" - {exam.subject.name}"

    # Get seat assignment info
    seat_info = getattr(enrollment, "seat_assignment", None)
    hall_name = seat_info.hall.name if seat_info else ""
    seat_number = str(seat_info.seat_number) if seat_info else ""

    return [
        exam_name,
        exam.program.name,
        exam.subject.name if exam.subject else "",
        session.base_start.strftime("%Y-%m-%d %H:%M:%S"),
        str(enrollment.individual_duration),
        exam.total_marks,
        hall_name,
        seat_number,
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
