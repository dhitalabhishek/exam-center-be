from functools import wraps

from django.contrib.admin.models import CHANGE
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType


def log_view_action(get_obj_func, action_flag=CHANGE, message=""):
    """
    Decorator to log user actions via Django views to LogEntry.

    Args:
        get_obj_func: A function that takes (request, *args, **kwargs)
        and returns the model instance to log.
        action_flag: One of ADDITION, CHANGE, DELETION
        message: Optional string for change_message
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)

            try:
                obj = get_obj_func(request, *args, **kwargs)
                if obj and request.user.is_authenticated:
                    LogEntry.objects.log_action(
                        user_id=request.user.pk,
                        content_type_id=ContentType.objects.get_for_model(obj).pk,
                        object_id=obj.pk,
                        object_repr=str(obj),
                        action_flag=action_flag,
                        change_message=message or f"Action on {obj.__class__.__name__}",
                    )
            except Exception as e:
                # Don't crash if logging fails
                print(f"LogEntry failed: {e}")  # noqa: T201

            return response
        return _wrapped_view
    return decorator
