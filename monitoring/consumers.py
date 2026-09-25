from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from monitoring.models import Project


class ProjectStreamConsumer(AsyncJsonWebsocketConsumer):
    group_prefix = "monitoring_project_"

    async def connect(self):
        user = self.scope.get("user")
        project_pk = self.scope["url_route"]["kwargs"].get("project_pk")
        if not project_pk or user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        if not await self._owns_project(user, project_pk):
            await self.close(code=4403)
            return
        self.group_name = f"{self.group_prefix}{project_pk}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    @database_sync_to_async
    def _owns_project(self, user, project_pk):
        return Project.objects.filter(pk=project_pk, owner=user).exists()

    async def disconnect(self, code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def monitoring_event(self, event):
        await self.send_json(
            {
                "type": event.get("type", "monitoring.event"),
                "payload": event.get("event", event.get("payload")),
            }
        )


class UserNotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        user_pk = self.scope["url_route"]["kwargs"].get("user_pk")
        if (
            user_pk is None
            or user is None
            or not user.is_authenticated
            or str(user.pk) != str(user_pk)
        ):
            await self.close(code=4401)
            return
        self.group_name = f"user_{user.pk}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def notification_message(self, event):
        await self.send_json(event.get("notification", event.get("payload")))
