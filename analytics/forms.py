from django import forms
from django.core.exceptions import ValidationError

from monitoring.models import Project


class DateRangeValidationMixin:
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError("The start date must not be after the end date")
        return cleaned_data


class ProjectScopedFilterForm(DateRangeValidationMixin, forms.Form):
    project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        empty_label="All projects",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        projects = Project.objects.all()
        if user is not None and getattr(user, "is_authenticated", False):
            projects = projects.filter(owner=user)
        self.fields["project"].queryset = projects.order_by("name")


class AnalyticsFilterForm(ProjectScopedFilterForm):
    date_from = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    date_to = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    event_type = forms.CharField(required=False, max_length=255)
    service = forms.CharField(required=False, max_length=255)
    environment = forms.CharField(required=False, max_length=255)
    status_code = forms.IntegerField(required=False)
    search = forms.CharField(required=False, max_length=255)


class ErrorMonitoringFilterForm(ProjectScopedFilterForm):
    date_from = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    date_to = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    service = forms.CharField(required=False, max_length=255)
    environment = forms.CharField(required=False, max_length=255)


class SlowRequestsFilterForm(ProjectScopedFilterForm):
    date_from = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    date_to = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    search = forms.CharField(required=False, max_length=255)
