# tokens.py
from rest_framework_simplejwt.tokens import AccessToken


class CustomAccessToken(AccessToken):
    @classmethod
    def for_user(cls, user):
        token = super().for_user(user)
        token["token_version"] = user.token_version
        return token


def get_tokens_for_user(user):
    user.token_version += 1
    user.save(update_fields=["token_version"])

    access = CustomAccessToken.for_user(user)
    return {
        "access": str(access),
    }
