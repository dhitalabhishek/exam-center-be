import json
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from appAuthentication.utils.closest_enrollment import get_closest_enrollment
from appCore.models import AdminNotification  # Ensure this is imported
from appCore.tasks import complete_expired_sessions
from appCore.tasks import submit_student_exam
from appCore.utils.redis_client import get_redis_client
from appExam.models import StudentExamEnrollment

logger = logging.getLogger(__name__)

UNAUTHORIZED_CODE = 4001
EVENT_TTL = 60  # seconds


class ExamStatusConsumer(AsyncJsonWebsocketConsumer):
    """Simplified WebSocket consumer for real-time exam status and timer control."""

    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            return await self.close(code=UNAUTHORIZED_CODE)

        await self.accept()
        self.enrollment = await self._fetch_enrollment()
        if not self.enrollment:
            await self.send_error("No active enrollment")
            return await self.close()

        await self._sync_and_start_timer()
        await self.send_status()  # noqa: RET503

    async def disconnect(self, code):
        await self._log_disconnect()

    async def receive_json(self, data, **kwargs):
        msg_type = data.get("type")
        handlers = {
            "ping": self._handle_ping,
            "status": self.send_status,
            "complete_check": self._handle_complete_check,
        }
        handler = handlers.get(msg_type, self._handle_unknown)
        await handler(data)

    # --- Handlers ---

    async def _handle_ping(self, data):
        await self.send_json({"type": "pong"})

    async def _handle_unknown(self, data):
        await self.send_error(f"Unknown type: {data.get('type')}")

    async def _handle_complete_check(self, data):
        await sync_to_async(complete_expired_sessions.delay)()
        await self.send_status()

    # --- Core logic ---

    @sync_to_async
    def _fetch_enrollment(self):
        try:
            return get_closest_enrollment(self.scope["user"].candidate_profile)
        except StudentExamEnrollment.DoesNotExist:
            return None

    @sync_to_async
    @transaction.atomic
    def _sync_and_start_timer(self):
        enroll = self.enrollment
        enroll.refresh_from_db()

        if enroll.session.status == "ongoing" and not enroll.present:
            enroll.handle_connect()

            remaining = enroll.effective_time_remaining.total_seconds()
            if remaining > 0:
                submit_student_exam.apply_async(
                    args=(enroll.id,),
                    countdown=remaining,
                    task_id=f"submit_exam_{enroll.id}",
                )
        return True

    @sync_to_async
    @transaction.atomic
    def _log_disconnect(self):
        enroll = self.enrollment
        if (
            enroll.present
            and enroll.session.status == "ongoing"
            and enroll.status != "submitted"
        ):
            enroll.handle_disconnect()

            AdminNotification.objects.create(
                text=f"{enroll.candidate.symbol_number} disconnected during the exam.",
                level="warning",
            )
        elif enroll.present:
            enroll.handle_disconnect()
        return True

    async def send_status(self, data=None):
        data = await self._gather_status()
        event = await self._pop_redis_event(self.enrollment.id)
        if event:
            data["event"] = event
        await self.send_json(
            {
                "type": "status",
                "data": data,
                "timestamp": timezone.localtime(timezone.now()).isoformat(),
            },
        )

    @sync_to_async
    def _gather_status(self):
        enroll = self.enrollment
        enroll.refresh_from_db()
        sess = enroll.session
        return {
            "status": enroll.status,
            "present": enroll.present,
            "session_status": sess.status,
            "time_remaining": max(0, enroll.effective_time_remaining.total_seconds()),
            "session_effective_end": (
                timezone.localtime(sess.expected_end).isoformat()
                if sess.expected_end
                else None
            ),
        }

    @sync_to_async
    def _pop_redis_event(self, eid):
        client = get_redis_client()
        key = f"exam_event_{eid}"
        raw = client.get(key)
        if raw:
            client.delete(key)
            try:
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                logger.error("Invalid JSON event for %s", key)  # noqa: TRY400
        return None

    async def send_error(self, msg):
        logger.error(msg)
        await self.send_json({"type": "error", "message": msg})
