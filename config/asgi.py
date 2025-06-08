# config/asgi.py

import os

import django
from channels.routing import ProtocolTypeRouter
from channels.routing import URLRouter
from django.core.asgi import get_asgi_application

from appCore.routing import get_websocket_urlpatterns
from backend.middleware import JWTAuthMiddleware

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

django.setup()


application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JWTAuthMiddleware(
        URLRouter(get_websocket_urlpatterns()),
    ),
})
