import json
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db import transaction
from django.utils import timezone

# Constants
UNAUTHORIZED_CODE = 4001
REDIS_EVENT_TTL = 60


class ExamStatusConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time exam status updates."""

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
        if message_type == "get_status":
            await self.send_current_status()
        elif message_type == "ping":
            await self.send_json({"type": "pong"})
        else:
            await self.send_error(f"Unknown message type: {message_type}")

    async def mark_student_active(self):
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
                enrollment = StudentExamEnrollment.objects.select_for_update().get(
                    candidate=self.user.candidate_profile,
                )
        except StudentExamEnrollment.DoesNotExist:
            return

        current_time = timezone.now()
        was_paused = enrollment.is_paused
        enrollment.last_activity = current_time

        if was_paused and enrollment.pause_started_at:
            pause_duration = current_time - enrollment.pause_started_at
            enrollment.total_pause_duration = (
                enrollment.total_pause_duration or timedelta()
            ) + pause_duration
            enrollment.is_paused = False
            enrollment.pause_started_at = None

            if enrollment.effective_time_remaining.total_seconds() > 0:
                expire_student_exam.apply_async(
                    args=(enrollment.id,),
                    countdown=enrollment.effective_time_remaining.total_seconds(),
                    task_id=f"expire_exam_{enrollment.id}",
                )
            else:
                enrollment.status = "submitted"

        # Always mark active if currently inactive
        if enrollment.status == "inactive":
            enrollment.status = "active"

        enrollment.save()

        if was_paused:
            redis_client = get_redis_client()
            redis_client.setex(
                f"exam_event_{enrollment.id}",
                REDIS_EVENT_TTL,
                json.dumps(
                    {"type": "exam_resumed", "timestamp": current_time.isoformat()},
                ),
            )

    async def mark_student_inactive(self):
        try:
            await database_sync_to_async(self._mark_inactive_sync)()
        except Exception:
            pass  # Don't raise errors on disconnect

    def _mark_inactive_sync(self):
        from celery import current_app

        from appCore.utils.redis_client import get_redis_client
        from appExam.models import StudentExamEnrollment

        try:
            enrollment = StudentExamEnrollment.objects.select_for_update().get(
                candidate=self.user.candidate_profile,
            )
        except StudentExamEnrollment.DoesNotExist:
            return

        if enrollment.status == "active" and not enrollment.is_paused:
            enrollment.is_paused = True
            enrollment.pause_started_at = timezone.now()
            enrollment.save(update_fields=["is_paused", "pause_started_at"])

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
        """Send current exam status."""
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
            )
        except StudentExamEnrollment.DoesNotExist:
            return None

    @database_sync_to_async
    def get_exam_status(self, enrollment, current_time):
        """Build exam status response."""
        return {
            "status": enrollment.status,
            "is_paused": enrollment.is_paused,
            "time_remaining": enrollment.effective_time_remaining.total_seconds(),
            "session_id": enrollment.session.id,
            "last_activity": timezone.localtime(enrollment.last_activity).strftime(
                "%Y-%m-%d %H:%M:%S"
            )  # noqa: E501
            if enrollment.last_activity
            else None,
        }

    async def send_error(self, message: str):
        """Send error message to client."""
        await self.send_json(
            {
                "type": "error",
                "message": message,
            },
        )

    async def send_json(self, data: dict):
        """Send JSON message to client."""
        await self.send(text_data=json.dumps(data))
