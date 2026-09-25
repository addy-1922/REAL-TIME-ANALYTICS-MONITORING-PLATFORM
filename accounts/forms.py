from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from .models import Profile


MAX_AVATAR_SIZE = 5 * 1024 * 1024


def validate_avatar(avatar):
    if avatar.size > MAX_AVATAR_SIZE:
        raise ValidationError("Profile picture must be 5 MB or smaller.")

    try:
        avatar.seek(0)
        with Image.open(avatar) as image:
            image.verify()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        TypeError,
        ValueError,
    ):
        raise ValidationError("Upload a valid image.") from None
    finally:
        avatar.seek(0)


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=False)

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")


class ProfileForm(forms.ModelForm):
    avatar = forms.ImageField(required=False, validators=[validate_avatar])

    class Meta:
        model = Profile
        fields = (
            "avatar",
            "bio",
            "job_title",
            "timezone",
            "daily_report_enabled",
        )
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
        }
