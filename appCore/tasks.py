import json
from datetime import datetime
from datetime import timedelta

from celery import current_app
from celery import shared_task
from django.utils import timezone
from utils.redis_client import get_redis_client

from appExam.models import ExamSession
from appExam.models import StudentExamEnrollment

redis_client = get_redis_client()
REDIS_KEY_PREFIX = "exam_task_last_run:"

SESSION_COMPLETION_CHECK_INTERVAL = 300  # seconds
INACTIVE_STUDENT_CHECK_INTERVAL = 120  # seconds


# ------------ Single Monitor Task Approach ------------
@shared_task
def exam_monitor():
    """Central task that coordinates all exam checks"""
    now = timezone.now()

    # Check for inactive students every 2 minutes
    last_run_inactive = redis_client.get(REDIS_KEY_PREFIX + "check_inactive_students")

    if (
        not last_run_inactive
        or (now - datetime.fromisoformat(last_run_inactive.decode())).total_seconds()
        >= INACTIVE_STUDENT_CHECK_INTERVAL
    ):
        check_inactive_students.delay()
        redis_client.set(REDIS_KEY_PREFIX + "check_inactive_students", now.isoformat())

    # Check session activation every minute
    activate_and_schedule_expiry.delay()
    last_run_completion = redis_client.get(
        REDIS_KEY_PREFIX + "check_session_completion",
    )
    if (
        not last_run_completion
        or (now - datetime.fromisoformat(last_run_completion.decode())).total_seconds()
        >= SESSION_COMPLETION_CHECK_INTERVAL
    ):
        check_session_completion.delay()
        redis_client.set(REDIS_KEY_PREFIX + "check_session_completion", now.isoformat())


# ------------ Core Exam Tasks (with early exits) ------------
@shared_task
def check_inactive_students():
    """Pause inactive students in ongoing sessions"""
    if not ExamSession.objects.filter(status="ongoing").exists():
        return "No ongoing sessions - skipping"

    threshold = timezone.now() - timedelta(seconds=90)
    qs = StudentExamEnrollment.objects.filter(
        status="active",
        last_activity__lt=threshold,
        is_paused=False,
        session__status="ongoing",
    )

    if not qs.exists():
        return "No inactive students found"

    for e in qs:
        e.is_paused = True
        e.pause_started_at = timezone.now()
        e.save(update_fields=["is_paused", "pause_started_at"])
        pause_for_inactivity.delay(e.id)

    return f"Paused {qs.count()} students"


@shared_task
def activate_and_schedule_expiry():
    """Activate scheduled sessions and set expiries"""
    now = timezone.now()
    sessions = ExamSession.objects.filter(status="scheduled", start_time__lte=now)

    if not sessions.exists():
        return "No sessions to activate"

    activated_count = 0
    for session in sessions:
        session.status = "ongoing"
        session.expected_end_time = session.end_time
        session.save(update_fields=["status", "expected_end_time"])

        enrollments = session.studentexamenrollment_set.filter(status="inactive")
        for e in enrollments:
            e.status = "active"
            e.save(update_fields=["status"])

            effective_end = session.expected_end_time + (
                session.total_pause_duration or timedelta(0)
            )
            expire_student_exam.apply_async(
                args=(e.id,),
                eta=effective_end,
                task_id=f"expire_exam_{e.id}",
            )

        activated_count += 1

    return f"Activated {activated_count} sessions"


@shared_task
def check_session_completion():
    """Mark sessions as completed when all students finish"""
    ongoing_sessions = ExamSession.objects.filter(status="ongoing")

    if not ongoing_sessions.exists():
        return "No ongoing sessions"

    completed_count = 0
    for session in ongoing_sessions:
        if not session.studentexamenrollment_set.exclude(status="submitted").exists():
            session.status = "completed"
            session.save(update_fields=["status"])
            completed_count += 1

    return f"Completed {completed_count} sessions"


# ------------ Supporting Tasks (unchanged) ------------
@shared_task
def pause_for_inactivity(enrollment_id):
    """Create pause event for inactive student"""
    payload = {"type": "inactivity_paused", "timestamp": timezone.now().isoformat()}
    redis_client.setex(f"exam_event_{enrollment_id}", 60, json.dumps(payload))


@shared_task
def expire_student_exam(enroll_id):
    """Submit exam accounting for pause state"""
    e = StudentExamEnrollment.objects.get(id=enroll_id)
    if e.status == "active" and not e.is_paused:
        e.status = "submitted"
        e.save(update_fields=["status"])
        payload = {"type": "exam_expired", "timestamp": timezone.now().isoformat()}
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))


# ------- halt / cancel exam session -------
@shared_task
def halt_exam_session(session_id, reason="admin_request"):
    """Halt exam session with pause handling"""
    enrollments = StudentExamEnrollment.objects.filter(
        session_id=session_id,
        status="active",
    )
    for e in enrollments:
        current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)
        e.status = "submitted"
        e.save(update_fields=["status"])
        payload = {
            "type": "session_halted",
            "reason": reason,
            "timestamp": timezone.now().isoformat(),
        }
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))
    ExamSession.objects.filter(id=session_id).update(status="cancelled")


@shared_task
def pause_exam_session(session_id):
    """Pause entire exam session"""
    session = ExamSession.objects.get(id=session_id)
    session.pause_started_at = timezone.now()
    session.save(update_fields=["pause_started_at"])

    # Revoke all expiry tasks
    enrollments = session.studentexamenrollment_set.filter(status="active")
    for e in enrollments:
        current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)

        # Pause individual students if not already paused
        if not e.is_paused:
            e.is_paused = True
            e.pause_started_at = timezone.now()
            e.save(update_fields=["is_paused", "pause_started_at"])

    # Send pause event to all students
    for e in enrollments:
        payload = {"type": "exam_paused", "timestamp": timezone.now().isoformat()}
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))


@shared_task
def resume_exam_session(session_id):
    """Resume paused exam session"""
    session = ExamSession.objects.get(id=session_id)
    if session.pause_started_at:
        pause_duration = timezone.now() - session.pause_started_at
        session.total_pause_duration += pause_duration
        session.pause_started_at = None
        session.end_time = session.expected_end_time + session.total_pause_duration
        session.save(
            update_fields=["pause_started_at", "total_pause_duration", "end_time"],
        )

    enrollments = session.studentexamenrollment_set.filter(
        status="active",
        is_paused=True,
    )

    for e in enrollments:
        # Resume individual students
        if e.pause_started_at:
            pause_duration = timezone.now() - e.pause_started_at
            e.total_pause_duration += pause_duration
            e.is_paused = False
            e.pause_started_at = None
            e.save(
                update_fields=["is_paused", "pause_started_at", "total_pause_duration"],
            )

        # Re-schedule expiry with new end time
        remaining = session.end_time - timezone.now()
        if remaining.total_seconds() > 0:
            task_id = f"expire_exam_{e.id}"
            expire_student_exam.apply_async(
                args=(e.id,),
                countdown=remaining.total_seconds(),
                task_id=task_id,
            )

        payload = {"type": "exam_resumed", "timestamp": timezone.now().isoformat()}
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))


@shared_task
def resume_student(enrollment_id):
    """Resume individual student after inactivity"""
    e = StudentExamEnrollment.objects.get(id=enrollment_id)
    if e.is_paused and e.pause_started_at:
        pause_duration = timezone.now() - e.pause_started_at
        e.total_pause_duration += pause_duration
        e.is_paused = False
        e.pause_started_at = None
        e.save(update_fields=["is_paused", "pause_started_at", "total_pause_duration"])

        # Recalculate time remaining
        session = e.session
        elapsed = timezone.now() - session.start_time
        base_remaining = session.duration - elapsed
        effective_remaining = (
            base_remaining - session.total_pause_duration - e.total_pause_duration
        )

        # Schedule new expiry
        task_id = f"expire_exam_{e.id}"
        expire_student_exam.apply_async(
            args=(e.id,),
            countdown=effective_remaining.total_seconds(),
            task_id=task_id,
        )

        payload = {"type": "exam_resumed", "timestamp": timezone.now().isoformat()}
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))
