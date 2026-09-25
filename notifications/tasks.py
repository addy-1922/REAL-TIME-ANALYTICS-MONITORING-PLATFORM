from smtplib import SMTPException

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import DatabaseError

from .models import Notification


@shared_task(
    autoretry_for=(DatabaseError, SMTPException, ConnectionError),
    retry_backoff=True,
    max_retries=getattr(settings, "NOTIFICATION_EMAIL_MAX_RETRIES", 3),
    default_retry_delay=getattr(settings, "NOTIFICATION_EMAIL_RETRY_DELAY", 60),
)
def send_notification_email(notification_id):
    try:
        notification = Notification.objects.select_related("user").get(
            pk=notification_id
        )
    except Notification.DoesNotExist:
        return 0

    if not notification.user.email:
        return 0

    return send_mail(
        subject=notification.title,
        message=notification.message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[notification.user.email],
        fail_silently=False,
    )
