# appAuthentication/utils/ajax_views.py

from django.contrib.auth import get_user_model
from django.http import JsonResponse

User = get_user_model()

def check_admin_second_password(request):
    email = request.GET.get("email")
    try:
        user = User.objects.get(email=email)
        has_second_password = bool(user.admin_password2)
    except User.DoesNotExist:
        has_second_password = False
    return JsonResponse({"require_second_password": has_second_password})
