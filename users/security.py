from django.contrib import messages
from django.shortcuts import redirect

from users.models import SecurityEvent


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def log_security_event(request, event_type: str, *, detail: str = "", user=None):
    SecurityEvent.objects.create(
        user=user if user is not None else (request.user if getattr(request, "user", None) and request.user.is_authenticated else None),
        event_type=event_type,
        path=(request.path or "")[:255],
        detail=detail,
        ip_address=_client_ip(request),
    )


def deny_with_audit(request, message: str, *, redirect_to: str = "profile"):
    log_security_event(request, "access_denied", detail=message)
    messages.error(request, message)
    return redirect(redirect_to)
