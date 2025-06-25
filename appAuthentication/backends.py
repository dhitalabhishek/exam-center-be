
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()

class DualPasswordBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        try:
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            return None

        # Allow login using either default password or admin_password2
        if user.check_password(password):
            return user

        if user.is_admin and user.check_admin_password2(password):
            return user

        return None
