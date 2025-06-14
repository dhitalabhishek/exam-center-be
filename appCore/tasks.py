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
REDIS_KEY_PREFIX = "exam_task_last_run:"
SESSION_COMPLETION_CHECK_INTERVAL = 300  # seconds
SESSION_COMPLETION_BUFFER = 60  # seconds grace period after effective end


@shared_task
def exam_monitor():
    """Central task that coordinates all exam checks"""
    now = timezone.now()

    # Check session activation every minute
    activate_and_schedule_expiry.delay()

    # Check session completion every SESSION_COMPLETION_CHECK_INTERVAL seconds
    last_run = redis_client.get(REDIS_KEY_PREFIX + "check_session_completion")
    last_ts = 0.0
    if last_run:
        raw = last_run.decode()
        try:
            last_ts = float(raw)
        except ValueError:
            # fallback to ISO format parsing
            try:
                last_dt = timezone.datetime.fromisoformat(raw)
                # Assuming ISO string may not be timezone-aware
                if timezone.is_naive(last_dt):
                    last_dt = timezone.make_aware(last_dt)
                last_ts = last_dt.timestamp()
            except Exception:
                last_ts = 0.0
    # schedule completion check if interval passed
    if now.timestamp() - last_ts >= SESSION_COMPLETION_CHECK_INTERVAL:
        check_session_completion.delay()
        # store as timestamp
        redis_client.set(
            REDIS_KEY_PREFIX + "check_session_completion",
            str(now.timestamp()),
        )


@shared_task
def activate_and_schedule_expiry():
    """Activate scheduled sessions and schedule expiry tasks"""
    now = timezone.now()
    activated_count = 0

    # Lock scheduled sessions to avoid double activation
    with transaction.atomic():
        sessions = ExamSession.objects.select_for_update(skip_locked=True).filter(
            status="scheduled", start_time__lte=now,
        )
        for session in sessions:
            session.status = "ongoing"
            session.expected_end_time = session.end_time
            session.save(update_fields=["status", "expected_end_time"])

            enrollments = session.studentexamenrollment_set.filter(status="inactive")
            for e in enrollments:
                # mark student active
                e.status = "active"
                e.save(update_fields=["status"])

                # revoke any existing expiry
                current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)

                # schedule new expiry
                effective_end = session.expected_end_time + (
                    session.total_pause_duration or timedelta(0)
                )
                task_id = f"expire_exam_{e.id}_{int(effective_end.timestamp())}"
                expire_student_exam.apply_async(
                    args=(e.id,),
                    eta=effective_end,
                    task_id=task_id,
                )
            activated_count += 1
    return f"Activated {activated_count} sessions"


@shared_task
def check_session_completion():
    """Mark sessions as completed when all students finish"""
    now = timezone.now()
    completed_count = 0

    sessions = ExamSession.objects.filter(status="ongoing")
    for session in sessions:
        eff_end = session.effective_end_time
        # require after grace period
        if eff_end and now >= eff_end + timedelta(seconds=SESSION_COMPLETION_BUFFER):
            # all submitted?
            if not session.studentexamenrollment_set.exclude(
                status="submitted",
            ).exists():
                session.status = "completed"
                session.save(update_fields=["status"])
                completed_count += 1
    return f"Completed {completed_count} sessions"


@shared_task
def expire_student_exam(enroll_id):
    """Submit exam accounting for pause state"""
    try:
        e = StudentExamEnrollment.objects.get(id=enroll_id)
    except StudentExamEnrollment.DoesNotExist:
        return

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


@shared_task
def pause_exam_session(session_id):
    """Pause entire exam session"""
    session = ExamSession.objects.get(id=session_id)
    session.pause_started_at = timezone.now()
    session.save(update_fields=["pause_started_at"])

    enrollments = session.studentexamenrollment_set.filter(status="active")
    for e in enrollments:
        current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)
        if not e.is_paused:
            e.is_paused = True
            e.pause_started_at = timezone.now()
            e.save(update_fields=["is_paused", "pause_started_at"])

    for e in enrollments:
        payload = {"type": "exam_paused", "timestamp": timezone.now().isoformat()}
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))


@shared_task
def resume_exam_session(session_id):
    """Resume paused exam session"""
    session = ExamSession.objects.get(id=session_id)
    if session.pause_started_at:
        now = timezone.now()
        pause_dur = now - session.pause_started_at
        session.total_pause_duration += pause_dur
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
        if e.pause_started_at:
            now = timezone.now()
            pd = now - e.pause_started_at
            e.total_pause_duration += pd
            e.is_paused = False
            e.pause_started_at = None
            e.save(
                update_fields=["is_paused", "pause_started_at", "total_pause_duration"],
            )

        remaining = session.end_time - timezone.now()
        if remaining.total_seconds() > 0:
            current_app.control.revoke(f"expire_exam_{e.id}", terminate=True)
            task_id = (
                f"expire_exam_{e.id}_{int((timezone.now() + remaining).timestamp())}"
            )
            expire_student_exam.apply_async(
                args=(e.id,),
                countdown=remaining.total_seconds(),
                task_id=task_id,
            )
        payload = {"type": "exam_resumed", "timestamp": timezone.now().isoformat()}
        redis_client.setex(f"exam_event_{e.id}", 60, json.dumps(payload))
