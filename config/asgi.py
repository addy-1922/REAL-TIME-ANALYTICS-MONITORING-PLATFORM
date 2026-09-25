"""ASGI entry point serving both HTTP and WebSocket traffic.

Import order matters here. ``monitoring.routing`` and ``notifications.routing``
import their consumers, and those consumers import ``monitoring.models`` at
module level. Defining a ``models.Model`` subclass requires a populated app
registry, so those imports must happen *after* Django has been set up. Calling
``get_asgi_application()`` runs ``django.setup()`` internally, so it doubles as
the initialisation point and must precede the routing imports below.

Importing the routing modules at the top of this file, before that call, is what
raises ``AppRegistryNotReady: Apps aren't loaded yet.``
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Runs django.setup(), which populates the app registry. Everything imported
# after this line may safely touch Django models.
from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from monitoring.routing import websocket_urlpatterns as monitoring_urlpatterns  # noqa: E402
from notifications.routing import (  # noqa: E402
    websocket_urlpatterns as notification_urlpatterns,
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter([*monitoring_urlpatterns, *notification_urlpatterns])
            )
        ),
    }
)
