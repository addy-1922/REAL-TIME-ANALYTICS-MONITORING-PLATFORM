from collections.abc import Mapping

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def _normalize(value):
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _validation_details(exception):
    detail = getattr(exception, "detail", None)
    if isinstance(detail, Mapping):
        return _normalize(detail)
    if isinstance(detail, list):
        return {"non_field_errors": _normalize(detail)}
    message_dict = getattr(exception, "message_dict", None)
    if isinstance(message_dict, Mapping):
        return _normalize(message_dict)
    messages = getattr(exception, "messages", None)
    if messages:
        return {"non_field_errors": _normalize(messages)}
    return {}


def _error_code(exception, status_code):
    if isinstance(exception, (exceptions.ValidationError, DjangoValidationError)):
        return "validation_error"
    if isinstance(exception, exceptions.NotAuthenticated):
        return "not_authenticated"
    if isinstance(exception, exceptions.AuthenticationFailed):
        return "authentication_failed"
    if isinstance(exception, (exceptions.PermissionDenied, DjangoPermissionDenied)):
        return "permission_denied"
    if isinstance(exception, (exceptions.NotFound, Http404, ObjectDoesNotExist)):
        return "not_found"
    if isinstance(exception, exceptions.MethodNotAllowed):
        return "method_not_allowed"
    if isinstance(exception, exceptions.UnsupportedMediaType):
        return "unsupported_media_type"
    if isinstance(exception, exceptions.ParseError):
        return "invalid_request"
    if isinstance(exception, exceptions.Throttled):
        return "throttled"
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "authentication_failed"
    if status_code == 403:
        return "permission_denied"
    if status_code == 404:
        return "not_found"
    if status_code == 405:
        return "method_not_allowed"
    if status_code == 406:
        return "not_acceptable"
    if status_code == 409:
        return "conflict"
    if status_code == 415:
        return "unsupported_media_type"
    if status_code == 429:
        return "throttled"
    if status_code >= 500:
        return "internal_server_error"
    return "api_error"


def _error_message(code, status_code):
    return {
        "validation_error": "Request validation failed.",
        "authentication_failed": "Authentication failed.",
        "not_authenticated": "Authentication required.",
        "permission_denied": "Permission denied.",
        "not_found": "Resource not found.",
        "method_not_allowed": "Method not allowed.",
        "not_acceptable": "Not acceptable.",
        "unsupported_media_type": "Unsupported media type.",
        "invalid_request": "Malformed request.",
        "throttled": "Request throttled.",
        "conflict": "Conflict.",
        "internal_server_error": "Internal server error.",
        "bad_request": "Bad request.",
    }.get(code, "API request failed.")


def api_exception_handler(exception, context):
    response = drf_exception_handler(exception, context)
    if response is None and isinstance(exception, DjangoValidationError):
        response = Response(status=status.HTTP_400_BAD_REQUEST)
    if response is None and isinstance(exception, DjangoPermissionDenied):
        response = Response(status=status.HTTP_403_FORBIDDEN)
    if response is None and isinstance(exception, (Http404, ObjectDoesNotExist)):
        response = Response(status=status.HTTP_404_NOT_FOUND)
    if response is None and isinstance(exception, Exception):
        response = Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    if response is None:
        return None

    response_status = response.status_code
    code = _error_code(exception, response_status)
    details = _validation_details(exception) if code == "validation_error" else {}
    payload = {
        "error": {
            "code": code,
            "message": _error_message(code, response_status),
            "details": details,
        }
    }
    headers = {}
    for header in ("Allow", "Retry-After", "WWW-Authenticate"):
        if header in response:
            headers[header] = response[header]
    return Response(payload, status=response_status, headers=headers)
