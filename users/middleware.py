from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

from users.security import log_security_event


class SessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now_ts = int(timezone.now().timestamp())
            last_seen = request.session.get("last_seen_ts")
            timeout_seconds = int(getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 1800))
            if last_seen and (now_ts - int(last_seen)) > timeout_seconds:
                log_security_event(request, "session_timeout", detail="Session expired due to inactivity.")
                logout(request)
                messages.info(request, "Session expired due to inactivity. Please sign in again.")
                return redirect("login")
            request.session["last_seen_ts"] = now_ts
        return self.get_response(request)
