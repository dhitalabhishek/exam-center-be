from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .models import CeleryTask


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
def log_view(request):
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
    paginator = Paginator(logs, 200)  # Show 50 logs per page
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
