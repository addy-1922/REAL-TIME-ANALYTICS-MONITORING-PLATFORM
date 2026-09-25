from django.urls import re_path

from monitoring import consumers

websocket_urlpatterns = [
    re_path(
        r"^ws/projects/(?P<project_pk>[0-9]+)/stream/$",
        consumers.ProjectStreamConsumer.as_asgi(),
    ),
    re_path(
        r"^ws/users/(?P<user_pk>[0-9]+)/notifications/$",
        consumers.UserNotificationConsumer.as_asgi(),
    ),
]