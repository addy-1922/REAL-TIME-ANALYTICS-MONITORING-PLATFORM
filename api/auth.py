import hashlib
import hmac

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from monitoring.models import Project


def generate_api_key():
    return Project.generate_api_key()


def hash_api_key(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _authorization_token(request):
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key.strip():
        return api_key.strip()

    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "apikey":
        return parts[1]
    return ""


class APIKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = _authorization_token(request)
        if not token:
            raise AuthenticationFailed("Invalid or missing API key.")

        candidate_hash = hash_api_key(token)
        try:
            project = Project.objects.select_related("owner").get(
                api_key_hash=candidate_hash
            )
        except Project.DoesNotExist as exc:
            raise AuthenticationFailed("Invalid or missing API key.") from exc

        if (
            not project.is_active
            or not project.api_key_hash
            or not hmac.compare_digest(str(project.api_key_hash), candidate_hash)
        ):
            raise AuthenticationFailed("Invalid or missing API key.")
        return project.owner, project

    def authenticate_header(self, request):
        return "ApiKey"


class APIKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "api.auth.APIKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "Project API key. Create a project in the SignalWatch UI and "
                "copy the key shown once after creation."
            ),
        }
