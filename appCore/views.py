import csv
import json
import logging
from datetime import timedelta

from celery import current_app
from django.contrib.admin.models import LogEntry
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appCore.tasks import expire_student_exam
from appCore.utils.redis_client import get_redis_client
from appExam.models import StudentExamEnrollment

from .models import CeleryTask

logger = logging.getLogger(__name__)
redis_client = get_redis_client()


# Action flag constants
ACTION_ADD = 1
ACTION_CHANGE = 2
ACTION_DELETE = 3


def get_enrollment_for_user(user):
    """
    Helper to fetch the active StudentExamEnrollment for the authenticated user
    """
    try:
        return StudentExamEnrollment.objects.select_for_update().get(
            student=user,
            session__status__in=["ongoing", "scheduled"],
        )
    except StudentExamEnrollment.DoesNotExist:
        return None


@never_cache
def task_last_updated(request):
    """Returns the timestamp of the most recently updated task"""
    last_task = CeleryTask.objects.order_by("-updated").first()
    return JsonResponse(
        {
            "last_updated": last_task.updated.timestamp() if last_task else 0,
        },
    )


def is_staff(user):
    return user.is_staff


@user_passes_test(is_staff)
def log_view(request):  # noqa: C901
    # Check if download is requested
    download_format = request.GET.get("download")
    if download_format in ["csv", "json"]:
        return download_logs(request, download_format)

    # Get filter parameters
    search_query = request.GET.get("search", "")
    user_filter = request.GET.get("user", "")
    action_filter = request.GET.get("action", "")
    time_filter = request.GET.get("time", "")

    # Start with all logs
    logs = LogEntry.objects.select_related("user", "content_type").order_by(
        "-action_time",
    )

    # Apply search filter
    if search_query:
        logs = logs.filter(
            Q(object_repr__icontains=search_query)
            | Q(change_message__icontains=search_query)
            | Q(user__email__icontains=search_query),
        )

    # Apply user filter
    if user_filter:
        logs = logs.filter(user__email__icontains=user_filter)

    # Apply action filter
    if action_filter:
        action_map = {"add": 1, "change": 2, "delete": 3}
        if action_filter.lower() in action_map:
            logs = logs.filter(action_flag=action_map[action_filter.lower()])

    # Apply time filter
    if time_filter:
        now = timezone.now()
        if time_filter == "1h":
            logs = logs.filter(action_time__gte=now - timedelta(hours=1))
        elif time_filter == "24h":
            logs = logs.filter(action_time__gte=now - timedelta(hours=24))
        elif time_filter == "7d":
            logs = logs.filter(action_time__gte=now - timedelta(days=7))
        elif time_filter == "30d":
            logs = logs.filter(action_time__gte=now - timedelta(days=30))

    # Get total count before pagination
    total_logs = logs.count()

    # Pagination
    from django.core.paginator import Paginator

    paginator = Paginator(logs, 50)  # Show 50 logs per page
    page_number = request.GET.get("page", 1)
    logs = paginator.get_page(page_number)

    # Get unique users for filter dropdown (limit and deduplicate properly)
    unique_users = list(
        LogEntry.objects.select_related("user")
        .values_list("user__email", flat=True)
        .distinct()
        .exclude(user__email__isnull=True)
        .order_by("user__email")[:100],
    )  # Limit to 100 unique users

    # Simple action statistics
    action_stats = {
        "total": total_logs,
    }

    context = {
        "logs": logs,
        "unique_users": unique_users,
        "action_stats": action_stats,
        "current_filters": {
            "search": search_query,
            "user": user_filter,
            "action": action_filter,
            "time": time_filter,
        },
        "has_previous": logs.has_previous(),
        "has_next": logs.has_next(),
        "page_number": logs.number,
        "total_pages": logs.paginator.num_pages,
        "total_logs": total_logs,
    }

    return render(request, "admin/appcore/logs.html", context)


def download_logs(request, format_type):  # noqa: C901
    """Download logs in CSV or JSON format"""
    # Get the same filters as the main view
    search_query = request.GET.get("search", "")
    user_filter = request.GET.get("user", "")
    action_filter = request.GET.get("action", "")
    time_filter = request.GET.get("time", "")

    # Apply same filtering logic
    logs = LogEntry.objects.select_related("user", "content_type").order_by(
        "-action_time",
    )

    if search_query:
        logs = logs.filter(
            Q(object_repr__icontains=search_query)
            | Q(change_message__icontains=search_query)
            | Q(user__email__icontains=search_query),
        )

    if user_filter:
        logs = logs.filter(user__email__icontains=user_filter)

    if action_filter:
        action_map = {"add": 1, "change": 2, "delete": 3}
        if action_filter.lower() in action_map:
            logs = logs.filter(action_flag=action_map[action_filter.lower()])

    if time_filter:
        now = timezone.now()
        if time_filter == "1h":
            logs = logs.filter(action_time__gte=now - timedelta(hours=1))
        elif time_filter == "24h":
            logs = logs.filter(action_time__gte=now - timedelta(hours=24))
        elif time_filter == "7d":
            logs = logs.filter(action_time__gte=now - timedelta(days=7))
        elif time_filter == "30d":
            logs = logs.filter(action_time__gte=now - timedelta(days=30))

    # Limit to 10000 records for download
    logs = logs[:10000]

    if format_type == "csv":
        return download_csv(logs)
    if format_type == "json":  # noqa: RET503
        return download_json(logs)


def download_csv(logs):
    """Export logs as CSV"""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="system_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'  # noqa: E501
    )

    writer = csv.writer(response)
    writer.writerow(["Date", "Time", "User", "Action", "Object", "Message"])

    for log in logs:
        action_text = ""
        if log.action_flag == ACTION_ADD:
            action_text = "ADD"
        elif log.action_flag == ACTION_CHANGE:
            action_text = "CHANGE"
        elif log.action_flag == ACTION_DELETE:
            action_text = "DELETE"

        writer.writerow(
            [
                log.action_time.strftime("%Y-%m-%d"),
                log.action_time.strftime("%H:%M:%S"),
                log.user.email if log.user else "System",
                action_text,
                log.object_repr,
                log.change_message.replace("\n", " ").replace("\r", " ")
                if log.change_message
                else "",
            ],
        )

    return response


def download_json(logs):
    """Export logs as JSON"""
    response = HttpResponse(content_type="application/json")
    response["Content-Disposition"] = (
        f'attachment; filename="system_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json"'  # noqa: E501
    )

    logs_data = []
    for log in logs:
        action_text = ""
        if log.action_flag == ACTION_ADD:
            action_text = "ADD"
        elif log.action_flag == ACTION_CHANGE:
            action_text = "CHANGE"
        elif log.action_flag == ACTION_DELETE:
            action_text = "DELETE"

        logs_data.append(
            {
                "date": log.action_time.strftime("%Y-%m-%d"),
                "time": log.action_time.strftime("%H:%M:%S"),
                "datetime": log.action_time.isoformat(),
                "user": log.user.email if log.user else "System",
                "action": action_text,
                "object": log.object_repr,
                "message": log.change_message if log.change_message else "",
            },
        )

    response.write(json.dumps(logs_data, indent=2))
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def student_heartbeat(request):
    """
    Handle student heartbeat using JWT authentication
    """
    enrollment = get_enrollment_for_user(request.user)
    if not enrollment:
        return Response({"error": "Enrollment not found"}, status=404)

    with transaction.atomic():
        e = StudentExamEnrollment.objects.select_for_update().get(id=enrollment.id)
        if e.status not in ["active", "inactive", "paused"]:
            return Response(
                {"error": "Exam session has ended", "status": e.status},
                status=400,
            )

        was_paused = e.is_paused
        current_time = timezone.now()
        actually_resumed = False
        pause_duration = timedelta(0)

        # Update last activity
        e.last_activity = current_time

        # Resume logic
        if was_paused and e.pause_started_at:
            pause_duration = max(timedelta(0), current_time - e.pause_started_at)
            e.total_pause_duration = (
                e.total_pause_duration or timedelta(0)
            ) + pause_duration
            e.is_paused = False
            e.pause_started_at = None
            e.status = "active"
            actually_resumed = True

            if e.effective_time_remaining.total_seconds() > 0:
                schedule_student_expiry(e)
            else:
                e.status = "submitted"

        # Save
        save_fields = ["last_activity"]
        if was_paused:
            save_fields += [
                "is_paused",
                "pause_started_at",
                "total_pause_duration",
                "status",
            ]
        e.save(update_fields=save_fields)

        # Redis events
        events = []
        event_key = f"exam_event_{e.id}"
        ev = redis_client.get(event_key)
        if ev:
            events.append(json.loads(ev))
            redis_client.delete(event_key)
        if actually_resumed:
            events.append(
                {
                    "type": "exam_resumed",
                    "timestamp": current_time.isoformat(),
                    "pause_duration": pause_duration.total_seconds(),
                },
            )

    return Response(
        {
            "heartbeat": current_time.isoformat(),
            "events": events,
            "action_required": "handle_events" if events else "none",
            "time_remaining": e.effective_time_remaining.total_seconds(),
            "status": e.status,
            "was_resumed": actually_resumed,
        },
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_exam_status(request):
    """
    Get current exam status for authenticated user
    """
    try:
        e = StudentExamEnrollment.objects.select_related("session").get(
            student=request.user,
        )
    except StudentExamEnrollment.DoesNotExist:
        return Response({"error": "Enrollment not found"}, status=404)

    # Status logic
    if e.is_paused:
        status = "paused"
    elif e.session.pause_started_at:
        status = "session_paused"
    else:
        status = e.status

    time_remaining = 0
    if status in ["active", "paused"]:
        time_remaining = max(0, e.effective_time_remaining.total_seconds())

    inactive_threshold = timezone.now() - timedelta(seconds=90)
    is_inactive = bool(
        e.last_activity and status == "active" and e.last_activity < inactive_threshold,
    )

    payload = {
        "status": status,
        "time_remaining": time_remaining,
        "is_inactive": is_inactive,
        "session_paused": bool(e.session.pause_started_at),
        "student_paused": e.is_paused,
        "last_activity": e.last_activity.isoformat() if e.last_activity else None,
        "total_pause_duration": (
            e.total_pause_duration or timedelta(0)
        ).total_seconds(),
    }

    # Redis last event
    ev = redis_client.get(f"exam_event_{e.id}")
    if ev:
        payload["last_event"] = json.loads(ev)

    return Response(payload)


# Helper function that could be added to the model
def schedule_student_expiry(enrollment):
    """
    Helper function to schedule student exam expiry
    Returns True if scheduled successfully, False otherwise
    """
    try:
        remaining_time = enrollment.effective_time_remaining

        if remaining_time.total_seconds() <= 0:
            return False

        # Cancel existing task
        current_app.control.revoke(f"expire_exam_{enrollment.id}", terminate=True)

        # Schedule new task
        expire_student_exam.apply_async(
            args=(enrollment.id,),
            countdown=remaining_time.total_seconds(),
            task_id=f"expire_exam_{enrollment.id}",
        )
        return True  # noqa: TRY300

    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to schedule expiry for enrollment {enrollment.id}: {e}")  # noqa: G004, TRY400
        return False
