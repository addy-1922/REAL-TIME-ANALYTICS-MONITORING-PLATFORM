from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from .models import Notification


def _broadcast(notification):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False
    async_to_sync(channel_layer.group_send)(
        f"user_{notification.user_id}",
        {
            "type": "notification_message",
            "notification": {
                "id": notification.id,
                "title": notification.title,
                "message": notification.message,
                "notification_type": notification.notification_type,
                "project_id": notification.project_id,
                "is_read": notification.is_read,
                "created_at": notification.created_at.isoformat(),
            },
        },
    )
    return True


def create_notification(user=None, project=None, title="", message="", notification_type="", **kwargs):
    user_id = kwargs.get("user_id")
    if user_id is None and user is not None:
        user_id = getattr(user, "pk", user)
    project_id = kwargs.get("project_id")
    if project_id is None and project is not None:
        project_id = getattr(project, "pk", project)

    with transaction.atomic():
        notification = Notification.objects.create(
            user_id=user_id,
            project_id=project_id,
            title=title,
            message=message,
            notification_type=notification_type,
        )
        transaction.on_commit(lambda: _broadcast(notification))
    return notification
