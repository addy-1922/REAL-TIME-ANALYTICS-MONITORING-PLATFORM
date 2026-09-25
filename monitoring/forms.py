from django import forms

from .models import AlertRule, Event, Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"autofocus": True}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class AlertRuleForm(forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = [
            "name",
            "metric",
            "condition",
            "threshold",
            "time_window_minutes",
            "cooldown_minutes",
            "is_active",
        ]
        widgets = {
            "metric": forms.Select(),
            "condition": forms.Select(),
            "threshold": forms.NumberInput(attrs={"step": "0.0001"}),
            "time_window_minutes": forms.NumberInput(attrs={"min": "1"}),
            "cooldown_minutes": forms.NumberInput(attrs={"min": "0"}),
        }


class EventFilterForm(forms.Form):
    event_type = forms.ChoiceField(
        label="Event type",
        choices=[("", "All event types")] + Event.EventType.choices,
        required=False,
    )
    custom_event_name = forms.CharField(
        label="Custom event name",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search custom event name"}),
    )
    service = forms.CharField(
        label="Service",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Exact service name"}),
    )
    environment = forms.CharField(
        label="Environment",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Exact environment"}),
    )
    status_code = forms.IntegerField(
        label="Status code",
        min_value=100,
        max_value=599,
        required=False,
        widget=forms.NumberInput(attrs={"placeholder": "e.g. 500"}),
    )
    date_from = forms.DateField(
        label="From date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label="To date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )