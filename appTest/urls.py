from django.http import JsonResponse

from .tasks import fake_task


def trigger_fake_task(request):
    task = fake_task.delay(3)  # runs fake_task asynchronously for 3 seconds
    return JsonResponse({"task_id": task.id, "status": "task started"})
