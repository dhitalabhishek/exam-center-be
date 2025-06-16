from urllib.parse import urlparse

import redis
from django.conf import settings


def get_redis_client():
    url = urlparse(settings.REDIS_URL)
    return redis.Redis(
        host=url.hostname,
        port=url.port,
        db=int(url.path.strip("/")) or 0,
        password=url.password,
        ssl=settings.REDIS_SSL,
    )
