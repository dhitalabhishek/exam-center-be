import json
from datetime import timedelta

from celery import current_app
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from appCore.utils.redis_client import get_redis_client
from appExam.models import ExamSession
from appExam.models import StudentExamEnrollment

redis_client = get_redis_client()

# Constants
REDIS_KEY_PREFIX = "exam_task_last_run:"
SESSION_COMPLETION_BUFFER = 60  # seconds grace period after effective end


@shared_task
def exam_monitor():
    """Central task that coordinates all exam checks."""
    activate_and_schedule_expiry.delay()
    check_student_connections.delay()
    check_session_completion.delay()


@shared_task
def check_student_connections():
    """Clear out any enrollments marked present but idle for >1 minute."""
    timeout = timedelta(minutes=1)
    cutoff = timezone.now() - timeout

    ghosts = StudentExamEnrollment.objects.filter(
        present=True,
        last_active_timestamp__lt=cutoff,
    )
    for e in ghosts:
        e.present = False
        if e.status == "active" and not e.is_paused:
            e.pause_exam_timer()
        e.save(update_fields=["present", "is_paused", "active_exam_time_used"])
    return f"Cleaned {ghosts.count()} ghost connections"


@shared_task
def check_session_completion():
    """Complete sessions whose effective end time has passed and no active students remain."""
    now = timezone.now()
    completed_count = 0

    # Only check ongoing sessions (not paused ones)
    sessions = ExamSession.objects.filter(status="ongoing")
    for session in sessions:
        if session.effective_end_time and now >= session.effective_end_time + timedelta(
            seconds=SESSION_COMPLETION_BUFFER,
        ):
            # Only consider students both active and still connected
            still_running = session.studentexamenrollment_set.filter(
                status="active",
                present=True,
            ).exists()

            if not still_running:
                session.status = "completed"
                session.save(update_fields=["status"])
                completed_count += 1

    return f"Completed {completed_count} sessions"


@shared_task
def halt_exam_session(session_id, reason="admin_request"):
    """Halt exam session with pause handling."""
    session = ExamSession.objects.get(id=session_id)

    enrollments = StudentExamEnrollment.objects.filter(
        session_id=session_id,
        status="active",
    )
    for e in enrollments:
        current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)
        e.status = "submitted"
        e.present = False
        e.stop_exam_timer()  # Stop individual timer
        e.save(
            update_fields=[
                "status",
                "present",
                "active_exam_time_used",
                "last_active_timestamp",
            ],
        )

        payload = {
            "type": "session_halted",
            "reason": reason,
            "timestamp": timezone.now().isoformat(),
        }
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))

    session.status = "cancelled"
    session.save(update_fields=["status"])


@shared_task
def activate_and_schedule_expiry():
    """Activate scheduled sessions and schedule expiry tasks."""
    now = timezone.now()
    activated_count = 0

    with transaction.atomic():
        sessions = ExamSession.objects.select_for_update(skip_locked=True).filter(
            status="scheduled",
            start_time__lte=now,
        )
        for session in sessions:
            session.status = "ongoing"
            session.save(update_fields=["status"])

            enrollments = session.studentexamenrollment_set.filter(status="inactive")
            for e in enrollments:
                e.status = "active"
                e.present = False  # students haven't connected yet
                e.start_exam_timer()
                e.save(update_fields=["status", "present"])

                # Schedule expiry based on individual student's time_remaining
                expire_student_exam.apply_async(
                    args=(e.id,),
                    countdown=e.time_remaining.total_seconds(),
                    task_id=f"expire_exam_{e.id}",
                )

            activated_count += 1

    return f"Activated {activated_count} sessions"


@shared_task
def pause_exam_session(session_id):
    """Pause entire exam session."""
    session = ExamSession.objects.get(id=session_id)

    # Pause the session itself
    session.pause_session()

    # Revoke all pending expiry tasks and pause individual student timers
    enrollments = session.studentexamenrollment_set.filter(status="active")

    for e in enrollments:
        # Revoke the expiry task
        current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)

        # Pause individual student timer if they're currently active
        if not e.is_paused:
            e.pause_exam_timer()

        payload = {
            "type": "exam_paused",
            "timestamp": timezone.now().isoformat(),
        }
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))

    return f"Paused session {session_id} with {enrollments.count()} active students"


@shared_task
def resume_exam_session(session_id):
    """Resume paused exam session."""
    session = ExamSession.objects.get(id=session_id)

    # Resume the session itself
    session.resume_session()

    # Resume individual student timers and reschedule expiry tasks
    enrollments = session.studentexamenrollment_set.filter(status="active")

    for e in enrollments:
        # Resume individual student timer if they were paused
        if e.is_paused:
            e.resume_exam_timer()

        # Calculate remaining time and reschedule expiry
        remaining_seconds = e.effective_time_remaining.total_seconds()
        if remaining_seconds > 0:
            expire_student_exam.apply_async(
                args=(e.id,),
                countdown=remaining_seconds,
                task_id=f"expire_exam_{e.id}",
            )
        else:
            # Time already expired, submit immediately
            expire_student_exam.delay(e.id)

        payload = {
            "type": "exam_resumed",
            "timestamp": timezone.now().isoformat(),
        }
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))

    return f"Resumed session {session_id} with {enrollments.count()} active students"


@shared_task
def expire_student_exam(enroll_id):
    """Submit exam when time expires and clear present flag."""
    try:
        e = StudentExamEnrollment.objects.get(id=enroll_id)
    except StudentExamEnrollment.DoesNotExist:
        return f"Enrollment {enroll_id} not found"

    # Only expire if student is still active
    if e.status == "active":
        e.stop_exam_timer()
        e.status = "submitted"
        e.present = False
        e.save(
            update_fields=[
                "status",
                "present",
                "active_exam_time_used",
                "last_active_timestamp",
            ],
        )

        payload = {
            "type": "exam_expired",
            "timestamp": timezone.now().isoformat(),
        }
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))

        return f"Expired exam for enrollment {enroll_id}"

    return f"Enrollment {enroll_id} already {e.status}"


@shared_task
def extend_session_time(session_id, additional_minutes):
    """Extend session time by specified minutes."""
    session = ExamSession.objects.get(id=session_id)

    if session.status not in ["ongoing", "paused"]:
        return f"Cannot extend session {session_id} - status is {session.status}"

    additional_time = timedelta(minutes=additional_minutes)

    # Update session end time
    if session.end_time:
        session.end_time += additional_time
    if session.expected_end_time:
        session.expected_end_time += additional_time
    session.save(update_fields=["end_time", "expected_end_time"])

    # Update student time allocations and reschedule expiry tasks
    enrollments = session.studentexamenrollment_set.filter(status="active")

    for e in enrollments:
        # Revoke existing expiry task
        current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)

        # Add time to student allocation
        e.time_remaining += additional_time
        e.save(update_fields=["time_remaining"])

        # Reschedule expiry task if session is not paused
        if session.status == "ongoing":
            remaining_seconds = e.effective_time_remaining.total_seconds()
            if remaining_seconds > 0:
                expire_student_exam.apply_async(
                    args=(e.id,),
                    countdown=remaining_seconds,
                    task_id=f"expire_exam_{e.id}",
                )

    return f"Extended session {session_id} by {additional_minutes} minutes for {enrollments.count()} students"
