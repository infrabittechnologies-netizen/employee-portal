import re

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.urls import reverse

# Matches phones and tablets. Desktops/laptops (Windows, macOS, Linux,
# Chrome OS) do not contain these tokens.
MOBILE_UA_RE = re.compile(
    r"(Mobi|Android|iPhone|iPod|iPad|Windows Phone|IEMobile|BlackBerry|"
    r"Opera Mini|Opera Mobi|webOS|Kindle|Silk|BB10|Tablet|Mobile Safari)",
    re.IGNORECASE,
)


class DesktopOnlyMiddleware:
    """Blocks every request coming from a mobile/tablet device.

    The portal is for office check-in on a laptop/Mac only, so phones and
    tablets get a professional block page instead of any access or login.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ua = request.META.get("HTTP_USER_AGENT", "")
        if MOBILE_UA_RE.search(ua):
            return render(request, "desktop_only.html", status=403)
        return self.get_response(request)


class EmployeeAutoLogoutMiddleware:
    """Automatically signs employees out once the working day is over.

    The shift ends at SHIFT_END (11:00 PM PKT); employees get a short grace
    window and are then logged out (11:10 PM – midnight PKT). Admins and
    superusers are exempt — they manage the team outside shift hours.

    This is the server-side guarantee; the front-end also triggers a graceful
    logout at the same cutoff so an idle, open tab signs itself out.
    """

    # Paths we must never bounce (auth flow + static/media) to avoid loops.
    _EXEMPT_PREFIXES = ("/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.is_admin
            and not request.path.startswith(self._EXEMPT_PREFIXES)
        ):
            from attendance.schedule import is_past_auto_logout

            if is_past_auto_logout():
                logout(request)
                messages.info(
                    request,
                    "Your shift has ended for today. You have been signed out "
                    "automatically. See you next shift!",
                )
                return redirect(reverse("accounts:login"))
        return self.get_response(request)
