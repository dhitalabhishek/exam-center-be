import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db import transaction
from django.utils import timezone

# Constants
UNAUTHORIZED_CODE = 4001
REDIS_EVENT_TTL = 60


class ExamStatusConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for on-demand exam status updates."""

    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close(code=UNAUTHORIZED_CODE)
            return

        await self.accept()
        await self.mark_student_active()
        await self.send_initial_status()

    async def disconnect(self, close_code):
        await self.mark_student_inactive()

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON format")
            return

        message_type = data.get("type")
        if message_type == "status_update":
            await self.send_current_status()
        elif message_type == "ping":
            await self.send_json({"type": "pong"})
        else:
            await self.send_error(f"Unknown message type: {message_type}")

    async def mark_student_active(self):
        """Mark student as active (present) and handle resume logic."""
        try:
            await database_sync_to_async(self._mark_active_sync)()
        except Exception as e:
            await self.send_error(f"Failed to mark active: {e!s}")

    def _mark_active_sync(self):
        from appCore.tasks import expire_student_exam
        from appCore.utils.redis_client import get_redis_client
        from appExam.models import StudentExamEnrollment

        try:
            with transaction.atomic():
                enrollment = (
                    StudentExamEnrollment.objects.select_for_update()
                    .select_related("session")
                    .get(
                        candidate=self.user.candidate_profile,
                        status__in=[
                            "inactive",
                            "active",
                        ],  # Only get active enrollments
                    )
                )
        except StudentExamEnrollment.DoesNotExist:
            return

        # Mark student as present
        enrollment.present = True

        # Check if session is paused - don't resume individual timer if session is paused
        session_is_paused = enrollment.session.is_session_paused
        current_time = timezone.now()
        was_individually_paused = enrollment.is_paused

        # Only resume individual timer if session is not paused
        if was_individually_paused and not session_is_paused:
            enrollment.resume_exam_timer()
            remaining_seconds = enrollment.effective_time_remaining.total_seconds()

            if remaining_seconds > 0:
                expire_student_exam.apply_async(
                    args=(enrollment.id,),
                    countdown=remaining_seconds,
                    task_id=f"expire_exam_{enrollment.id}",
                )
            else:
                # Time expired, submit exam
                enrollment.stop_exam_timer()
                enrollment.status = "submitted"
                enrollment.save(
                    update_fields=[
                        "status",
                        "present",
                        "active_exam_time_used",
                        "last_active_timestamp",
                    ],
                )
                return

        # Handle activation from inactive state (only if session is not paused)
        elif enrollment.status == "inactive" and not session_is_paused:
            enrollment.status = "active"
            enrollment.start_exam_timer()
            remaining_seconds = enrollment.effective_time_remaining.total_seconds()

            if remaining_seconds > 0:
                expire_student_exam.apply_async(
                    args=(enrollment.id,),
                    countdown=remaining_seconds,
                    task_id=f"expire_exam_{enrollment.id}",
                )
            else:
                # Time expired immediately
                enrollment.stop_exam_timer()
                enrollment.status = "submitted"
                enrollment.save(
                    update_fields=[
                        "status",
                        "present",
                        "active_exam_time_used",
                        "last_active_timestamp",
                    ],
                )
                return

        # Save the present status regardless
        enrollment.save(update_fields=["present"])

        # Queue resume event only if we actually resumed
        if was_individually_paused and not session_is_paused:
            redis_client = get_redis_client()
            redis_client.setex(
                f"exam_event_{enrollment.id}",
                REDIS_EVENT_TTL,
                json.dumps(
                    {"type": "exam_resumed", "timestamp": current_time.isoformat()},
                ),
            )
        elif session_is_paused:
            # Notify client that session is paused
            redis_client = get_redis_client()
            redis_client.setex(
                f"exam_event_{enrollment.id}",
                REDIS_EVENT_TTL,
                json.dumps(
                    {
                        "type": "session_paused",
                        "message": "Session is currently paused",
                        "timestamp": current_time.isoformat(),
                    },
                ),
            )

    async def mark_student_inactive(self):
        """Mark student as inactive (paused) and clear present flag."""
        try:
            await database_sync_to_async(self._mark_inactive_sync)()
        except Exception:
            pass

    def _mark_inactive_sync(self):
        from celery import current_app

        from appCore.utils.redis_client import get_redis_client
        from appExam.models import StudentExamEnrollment

        try:
            with transaction.atomic():
                enrollment = (
                    StudentExamEnrollment.objects.select_for_update()
                    .select_related("session")
                    .get(
                        candidate=self.user.candidate_profile,
                        status__in=["active", "inactive"],
                    )
                )
        except StudentExamEnrollment.DoesNotExist:
            return

        # Clear present flag
        enrollment.present = False

        # Only pause individual timer if student is active and not already paused
        # and if the session itself is not paused (to avoid double-pausing)
        if (
            enrollment.status == "active"
            and not enrollment.is_paused
            and not enrollment.session.is_session_paused
        ):
            enrollment.pause_exam_timer()
            current_app.control.revoke(f"expire_exam_{enrollment.id}", terminate=True)

            redis_client = get_redis_client()
            redis_client.setex(
                f"exam_event_{enrollment.id}",
                REDIS_EVENT_TTL,
                json.dumps(
                    {
                        "type": "connection_lost_paused",
                        "timestamp": timezone.now().isoformat(),
                    },
                ),
            )

        enrollment.save(update_fields=["present"])

    async def send_initial_status(self):
        """Send initial exam status on connection."""
        try:
            enrollment = await self.get_user_enrollment()
            if not enrollment:
                await self.send_error("Enrollment not found")
                return

            now = timezone.now()
            status_data = await self.get_exam_status(enrollment, now)

            await self.send_json(
                {
                    "type": "initial_status",
                    "data": status_data,
                    "timestamp": now.isoformat(),
                },
            )
        except Exception as e:
            await self.send_error(f"Failed to get initial status: {e!s}")

    async def send_current_status(self):
        """Send current exam status on client request."""
        try:
            enrollment = await self.get_user_enrollment()
            if not enrollment:
                await self.send_error("Enrollment not found")
                return

            now = timezone.now()
            status_data = await self.get_exam_status(enrollment, now)

            from appCore.utils.redis_client import get_redis_client

            redis_client = get_redis_client()
            event_key = f"exam_event_{enrollment.id}"
            event = await database_sync_to_async(redis_client.get)(event_key)

            if event:
                status_data["last_event"] = json.loads(event)
                await database_sync_to_async(redis_client.delete)(event_key)

            await self.send_json(
                {
                    "type": "status_update",
                    "data": status_data,
                    "timestamp": now.isoformat(),
                },
            )
        except Exception as e:
            await self.send_error(f"Failed to get status: {e!s}")

    @database_sync_to_async
    def get_user_enrollment(self):
        from appExam.models import StudentExamEnrollment

        try:
            return StudentExamEnrollment.objects.select_related("session").get(
                candidate=self.user.candidate_profile,
                status__in=[
                    "inactive",
                    "active",
                    "submitted",
                ],  # Include all relevant statuses
            )
        except StudentExamEnrollment.DoesNotExist:
            return None

    @database_sync_to_async
    def get_exam_status(self, enrollment, current_time):
        enrollment.refresh_from_db()
        enrollment.session.refresh_from_db()

        # Use the updated time calculation method that accounts for session pauses
        time_remaining = enrollment.effective_time_remaining
        time_remaining_seconds = (
            max(0, time_remaining.total_seconds()) if time_remaining else 0
        )

        # Get allocated time in seconds
        allocated_seconds = (
            enrollment.time_remaining.total_seconds()
            if enrollment.time_remaining
            else 0
        )

        # Calculate time used including session pauses
        total_time_used = enrollment.get_current_active_time_used().total_seconds()
        session_pause_time = (
            enrollment.session.total_session_pause_duration.total_seconds()
        )

        return {
            "status": enrollment.status,
            "is_paused": enrollment.is_paused,
            "session_paused": enrollment.session.is_session_paused,
            "session_status": enrollment.session.status,
            "time_remaining": time_remaining_seconds,
            "session_id": enrollment.session.id,
            "active_time_used": total_time_used,
            "session_pause_time": session_pause_time,
            "total_time_allocated": allocated_seconds,
            "effective_time_remaining": time_remaining_seconds,
            "last_active_timestamp": timezone.localtime(
                enrollment.last_active_timestamp,
            ).strftime("%Y-%m-%d %H:%M:%S")
            if enrollment.last_active_timestamp
            else None,
            "session_start_time": enrollment.session.start_time.isoformat(),
            "session_end_time": enrollment.session.end_time.isoformat()
            if enrollment.session.end_time
            else None,
            "session_effective_end_time": enrollment.session.effective_end_time.isoformat()
            if enrollment.session.effective_end_time
            else None,
        }

    async def send_error(self, message: str):
        await self.send_json({"type": "error", "message": message})

    async def send_json(self, data: dict):
        await self.send(text_data=json.dumps(data))
