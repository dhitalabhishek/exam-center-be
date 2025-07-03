import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from appCore.models import AdminNotification
from appCore.utils.redis_client import get_redis_client
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
    submit_expired_students.delay()
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
def submit_expired_students():
    """NEW: Submit individual students whose time has expired"""
    now = timezone.now()
    submitted = 0

    # Get all active/paused enrollments from ongoing sessions
    enrollments = StudentExamEnrollment.objects.filter(
        status__in=["active", "paused"],
        session__status__in=["ongoing", "paused"],
    ).select_related("session")

    for enrollment in enrollments:
        try:
            # Check if student's individual time has expired
            if enrollment.should_submit:
                if enrollment.submit_exam():
                    submitted += 1
                    logger.info(
                        f"Auto-submitted enrollment {enrollment.id} - time expired",  # noqa: G004
                    )
        except Exception as e:
            logger.error(f"Error checking enrollment {enrollment.id}: {e}")  # noqa: G004

    return f"Auto-submitted {submitted} students whose time expired"


@shared_task
def handle_student_disconnect(enrollment_id):
    """Process student disconnection and schedule submission"""
    try:
        enrollment = StudentExamEnrollment.objects.get(id=enrollment_id)

        # Just log disconnection without freezing/pause logic
        enrollment.handle_disconnect()

        # FIXED: Better handling of submission scheduling
        remaining_seconds = enrollment.effective_time_remaining.total_seconds()

        # If time already expired, submit immediately
        if remaining_seconds <= 0:
            submit_student_exam.delay(enrollment_id)
        else:
            # Schedule submission with minimum 1 second countdown to avoid timing issues
            countdown = max(1, int(remaining_seconds))
            submit_student_exam.apply_async((enrollment_id,), countdown=countdown)

        return f"Handled disconnect for {enrollment_id}"  # noqa: TRY300
    except StudentExamEnrollment.DoesNotExist:
        return f"Enrollment {enrollment_id} not found"


@shared_task
def submit_student_exam(enrollment_id):
    """Submit an individual student's exam"""
    try:
        enrollment = StudentExamEnrollment.objects.get(id=enrollment_id)
        if enrollment.status in ["active", "paused"]:
            if enrollment.submit_exam():
                logger.info(f"Successfully submitted enrollment {enrollment_id}")
                return f"Submitted enrollment {enrollment_id}"
            return f"Enrollment {enrollment_id} was already submitted"
        return (  # noqa: TRY300
            f"Enrollment {enrollment_id} not in submittable state: {enrollment.status}"
        )
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
                status="paused",
                paused_at__isnull=False,
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


@shared_task
def evaluate_disconnection_pause(enrollment_id):
    """Pause student individually if not reconnected in 10 seconds"""
    try:
        enrollment = StudentExamEnrollment.objects.get(id=enrollment_id)
        if not enrollment.present and enrollment.status == "active":
            now = timezone.now()
            if enrollment.disconnected_at:
                # Start individual pause
                enrollment.individual_paused_at = now
                enrollment.status = "paused"
                enrollment.save()
                return f"Enrollment {enrollment_id} individually paused"
        return f"Enrollment {enrollment_id} already reconnected"  # noqa: TRY300
    except StudentExamEnrollment.DoesNotExist:
        return f"Enrollment {enrollment_id} not found"


@shared_task
def force_submit_student(enrollment_id, reason="Manual override"):
    """NEW: Force submit a specific student (for admin use)"""
    try:
        enrollment = StudentExamEnrollment.objects.get(id=enrollment_id)
        if enrollment.status in ["active", "paused"]:
            if enrollment.submit_exam():
                logger.info(f"Force submitted enrollment {enrollment_id}: {reason}")
                return f"Force submitted enrollment {enrollment_id}: {reason}"
        return f"Enrollment {enrollment_id} already submitted"
    except StudentExamEnrollment.DoesNotExist:
        return f"Enrollment {enrollment_id} not found"


@shared_task
def notify_disconnected_candidates():
    client = get_redis_client()
    key = "disconnected_candidates"
    candidates = client.smembers(key)

    if candidates:
        # Convert from bytes to str if Redis returns bytes
        candidates = [
            c.decode("utf-8") if isinstance(c, bytes) else c for c in candidates
        ]

        # Compose single notification
        msg = f"Candidates disconnected in last 10s: {', '.join(candidates)}"

        AdminNotification.objects.create(
            text=msg,
            level="warning",
        )
        client.delete(key)
