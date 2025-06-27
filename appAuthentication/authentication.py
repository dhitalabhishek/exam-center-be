from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class CustomJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        token_version = validated_token.get("token_version")
        if token_version != user.token_version:
            msg = "Token invalidated. Please login again."
            raise AuthenticationFailed(msg)
        return user
