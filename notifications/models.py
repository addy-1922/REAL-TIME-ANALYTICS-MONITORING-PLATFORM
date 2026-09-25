from django.conf import settings
from django.db import models


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        ERROR_ALERT = "ERROR_ALERT", "Error alert"
        PERFORMANCE_ALERT = "PERFORMANCE_ALERT", "Performance alert"
        SYSTEM = "SYSTEM", "System"
        PROJECT = "PROJECT", "Project"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    project = models.ForeignKey(
        "monitoring.Project",
        on_delete=models.SET_NULL,
        related_name="notifications",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=32,
        choices=NotificationType.choices,
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="notif_user_created_idx"),
            models.Index(
                fields=["user", "is_read", "created_at"],
                name="notif_user_read_created_idx",
            ),
        ]

    def __str__(self):
        return self.title
