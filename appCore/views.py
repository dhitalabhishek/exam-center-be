from django.http import JsonResponse
from django.views.decorators.cache import never_cache

from .models import CeleryTask


@never_cache
def task_last_updated(request):
    """Returns the timestamp of the most recently updated task"""
    last_task = CeleryTask.objects.order_by("-updated").first()
    return JsonResponse({
        "last_updated": last_task.updated.timestamp() if last_task else 0,
    })
