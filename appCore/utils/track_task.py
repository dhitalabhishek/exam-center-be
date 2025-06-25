from contextlib import contextmanager

from appCore.models import AdminNotification
from appCore.models import CeleryTask


@contextmanager
def track_task(task_id, task_name):
    """
    Context manager for tracking Celery task progress.

    Usage:
    with track_task(task_id, 'task_name', notify_admin=True) as task:
        task.progress = 50
        task.message = "Processing..."
        task.save()
    """
    task, created = CeleryTask.objects.update_or_create(
        task_id=task_id,
        defaults={"name": task_name, "status": "STARTED"},
    )

    try:
        yield task
        task.status = "SUCCESS"
        task.progress = 100
        AdminNotification.objects.create(
            text=f"Task '{task.name}' completed successfully.",
            level="info",
        )
    except Exception as e:
        task.status = "FAILURE"
        task.message = f"Error: {e!s}"
        AdminNotification.objects.create(
            text=f"Task '{task.name}' failed: {e!s}",
            level="error",
        )
        raise
    finally:
        task.save()
