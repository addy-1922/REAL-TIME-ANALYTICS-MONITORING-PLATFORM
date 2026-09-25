from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from .forms import ProfileForm, RegistrationForm
from .models import Profile


User = get_user_model()


def get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class RegisterView(CreateView):
    model = User
    form_class = RegistrationForm
    template_name = "registration/register.html"
    success_url = reverse_lazy("accounts:login")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Your account has been created.")
        return response


class ProfileView(LoginRequiredMixin, DetailView):
    model = Profile
    context_object_name = "profile"
    template_name = "accounts/profile.html"

    def get_object(self, queryset=None):
        return get_profile(self.request.user)


class ProfileEditView(LoginRequiredMixin, UpdateView):
    model = Profile
    form_class = ProfileForm
    context_object_name = "profile"
    template_name = "accounts/profile_edit.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return get_profile(self.request.user)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Your profile has been updated.")
        return response


class ProfilePictureDeleteView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile_picture_delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile"] = get_profile(self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        profile = get_profile(request.user)
        if profile.avatar:
            profile.avatar.delete(save=True)
        messages.success(request, "Your profile picture has been deleted.")
        return redirect("accounts:profile")
