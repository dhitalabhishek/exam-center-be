import json
from datetime import timedelta

from celery import current_app
from celery import shared_task
from django.utils import timezone
from utils.redis_client import get_redis_client

from appExam.models import ExamSession
from appExam.models import StudentExamEnrollment

redis_client = get_redis_client()


@shared_task
def check_inactive_students():
    """Pause inactive students and schedule pause events"""
    threshold = timezone.now() - timedelta(seconds=90)
    qs = StudentExamEnrollment.objects.filter(
        status="active", last_activity__lt=threshold, is_paused=False,
    )
    for e in qs:
        e.is_paused = True
        e.pause_started_at = timezone.now()
        e.save(update_fields=["is_paused", "pause_started_at"])
        pause_for_inactivity.delay(e.id)


@shared_task
def pause_for_inactivity(enrollment_id):
    """Create pause event for inactive student"""
    payload = {"type": "inactivity_paused", "timestamp": timezone.now().isoformat()}
    redis_client.setex(f"exam_event_{enrollment_id}", 60, json.dumps(payload))


@shared_task
def activate_and_schedule_expiry():
    """Activate sessions and schedule expiry with pause handling"""
    now = timezone.now()
    sessions = ExamSession.objects.filter(status="scheduled", start_time__lte=now)

    for session in sessions:
        session.status = "ongoing"
        session.expected_end_time = session.end_time  # Store original end time
        session.save(update_fields=["status", "expected_end_time"])

        # duration = session.duration or timedelta()  # noqa: ERA001
        for e in session.studentexamenrollment_set.filter(status="inactive"):
            e.status = "active"
            e.save(update_fields=["status"])

            # Calculate effective end time with pauses
            effective_end = session.expected_end_time + session.total_pause_duration
            task_id = f"expire_exam_{e.id}"
            expire_student_exam.apply_async(
                args=(e.id,),
                eta=effective_end,
                task_id=task_id,
            )


@shared_task
def expire_student_exam(enroll_id):
    """Submit exam accounting for pause state"""
    e = StudentExamEnrollment.objects.get(id=enroll_id)
    if e.status == "active" and not e.is_paused:
        e.status = "submitted"
        e.save(update_fields=["status"])
        payload = {"type": "exam_expired", "timestamp": timezone.now().isoformat()}
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))


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


# New Tasks =========================================================


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
        status="active", is_paused=True,
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


@shared_task
def check_session_completion(session_id):
    """Mark session complete when all students submit"""
    session = ExamSession.objects.get(id=session_id)
    active_count = session.studentexamenrollment_set.filter(
        status__in=["active", "inactive"],
    ).count()

    if active_count == 0 and session.status == "ongoing":
        session.status = "completed"
        session.save(update_fields=["status"])
