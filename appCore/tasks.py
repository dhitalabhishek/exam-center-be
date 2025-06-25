import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from appExam.models import ExamSession
from appExam.models import StudentExamEnrollment

logger = logging.getLogger(__name__)

# Constants
SESSION_COMPLETION_BUFFER = 60  # seconds grace period after session end
CONNECTION_TIMEOUT = 15  # minutes


@shared_task
def exam_monitor():
    """Central task that coordinates all exam checks."""
    activate_scheduled_sessions.delay()
    complete_expired_sessions.delay()
    return "Exam monitoring tasks dispatched"


@shared_task
def activate_scheduled_sessions():
    """Activate sessions that have reached their start time"""
    now = timezone.now()
    activated = 0

    sessions = ExamSession.objects.filter(status="scheduled", base_start__lte=now)

    for session in sessions:
        if session.start_session():
            activated += 1

    return f"Activated {activated} sessions"


@shared_task
def complete_expired_sessions():
    """Complete sessions whose effective end time has passed"""
    now = timezone.now()
    completed = 0

    sessions = ExamSession.objects.filter(status__in=["ongoing", "paused"])

    for session in sessions:
        try:
            expected_end = (
                session.base_start + session.base_duration + session.total_paused
            )
            if expected_end <= now - timedelta(seconds=SESSION_COMPLETION_BUFFER):
                if session.end_session():
                    completed += 1
        except Exception:  # noqa: BLE001, S110
            pass

    return f"Completed {completed} sessions"


@shared_task
def handle_student_disconnect(enrollment_id):
    """Process student disconnection and schedule submission"""
    try:
        enrollment = StudentExamEnrollment.objects.get(id=enrollment_id)

        # Just log disconnection without freezing/pause logic
        enrollment.handle_disconnect()

        # Schedule submission if time expires
        remaining = enrollment.effective_time_remaining.total_seconds()

        if remaining > 0:
            submit_student_exam.apply_async((enrollment_id,), countdown=remaining)
        else:
            submit_student_exam.delay(enrollment_id)

        return f"Handled disconnect for {enrollment_id}"  # noqa: TRY300
    except StudentExamEnrollment.DoesNotExist:
        return f"Enrollment {enrollment_id} not found"


@shared_task
def submit_student_exam(enrollment_id):
    """Submit an individual student's exam"""
    try:
        enrollment = StudentExamEnrollment.objects.get(id=enrollment_id)
        if enrollment.status in ["active", "paused"]:
            enrollment.submit_exam()
            return f"Submitted enrollment {enrollment_id}"
        return f"Enrollment {enrollment_id} already submitted"  # noqa: TRY300
    except StudentExamEnrollment.DoesNotExist:
        return f"Enrollment {enrollment_id} not found"


@shared_task
def pause_exam_session(session_id):
    """Pause entire exam session"""
    try:
        session = ExamSession.objects.get(id=session_id)
        if session.status == "ongoing":
            session.pause_session()
            #  pause each student
            for enrollment in session.enrollments.filter(status="active"):
                enrollment.status = "paused"
                enrollment.paused_at = timezone.now()
                enrollment.save()
            return f"Paused session {session_id}"
        return f"Session {session_id} not in ongoing state"  # noqa: TRY300
    except ExamSession.DoesNotExist:
        return f"Session {session_id} not found"


@shared_task
def resume_exam_session(session_id):
    """Resume paused exam session"""
    try:
        session = ExamSession.objects.get(id=session_id)
        if session.status == "paused":
            session.resume_session()
            # Optional: resume each student
            for enrollment in session.enrollments.filter(
                status="paused", paused_at__isnull=False,
            ):
                pause_time = timezone.now() - enrollment.paused_at
                enrollment.paused_duration += pause_time
                enrollment.paused_at = None
                enrollment.status = "active"
                enrollment.save()
            return f"Resumed session {session_id}"
        return f"Session {session_id} not in paused state"  # noqa: TRY300
    except ExamSession.DoesNotExist:
        return f"Session {session_id} not found"


@shared_task
def halt_exam_session(session_id):
    """Immediately end an exam session (admin override)"""
    try:
        session = ExamSession.objects.get(id=session_id)
        session.status = "cancelled"
        session.save()

        # Submit all active/paused students
        enrollments = session.enrollments.filter(status__in=["active", "paused"])
        for enrollment in enrollments:
            enrollment.submit_exam()

        return f"Halted session {session_id}"  # noqa: TRY300
    except ExamSession.DoesNotExist:
        return f"Session {session_id} not found"
