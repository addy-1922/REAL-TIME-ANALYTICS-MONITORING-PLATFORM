from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    avatar = models.ImageField(upload_to="profile_pictures/", blank=True, null=True)
    bio = models.TextField(blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    daily_report_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ("user__username",)

    def __str__(self):
        return self.user.get_username()
