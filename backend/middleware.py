from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware

from config.settings.local import SECRET_KEY


@database_sync_to_async
def get_user(user_id):
    # Delay Django import until this function is called
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import AnonymousUser

    User = get_user_model()  # noqa: N806
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom middleware that takes a 'token' query param and authenticates the user.
    """

    async def __call__(self, scope, receive, send):
        from django.contrib.auth.models import AnonymousUser
        from rest_framework_simplejwt.backends import TokenBackend
        from rest_framework_simplejwt.exceptions import InvalidToken
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import UntypedToken

        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        token_list = params.get("token")

        if token_list:
            token = token_list[0]
            try:
                # Validate token and decode it
                UntypedToken(token)
                valid_data = TokenBackend(
                    algorithm="HS256",
                    signing_key=SECRET_KEY,
                ).decode(token, verify=True)
                user_id = valid_data["user_id"]
                scope["user"] = await get_user(user_id)
            except (InvalidToken, TokenError):
                scope["user"] = AnonymousUser()
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
