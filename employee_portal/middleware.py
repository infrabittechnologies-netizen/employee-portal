import ipaddress
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse


# ---------------------------------------------------------------------------
# IP allow-list helpers (reused by the middleware AND the login view)
# ---------------------------------------------------------------------------

def _is_public(token):
    try:
        ip = ipaddress.ip_address(token)
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback)


def get_client_ip(request):
    """Return the visitor's public client IP, or None for internal requests.

    Resolution order (Railway / Envoy edge proxy):

    1. ``X-Envoy-External-Address`` — Envoy (Railway's edge) sets this to the
       single real client address it observed. It is NOT client-controllable,
       so it is the most trustworthy source and we use it first.
    2. ``X-Forwarded-For`` — the real visitor is the LEFT-most entry; Railway
       appends its own proxy hop(s) on the right. We walk from the LEFT and
       return the first PUBLIC address. ``settings.PORTAL_IP_XFF_INDEX`` (if
       set to an integer) forces a fixed position instead.
    3. ``X-Real-IP`` — some proxies set this single value.

    None is returned when there is no forwarded chain at all (Railway health
    check on "/", the local dev server, or the test client) or when the whole
    chain is private — i.e. platform-internal traffic.
    """
    # 1. Envoy's trusted, non-spoofable real-client address.
    envoy = request.META.get("HTTP_X_ENVOY_EXTERNAL_ADDRESS", "").strip()
    if envoy and _is_public(envoy):
        return envoy

    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    parts = [p.strip() for p in xff.split(",") if p.strip()]

    if parts:
        idx = getattr(settings, "PORTAL_IP_XFF_INDEX", None)
        if idx is not None:
            try:
                return parts[idx]
            except IndexError:
                pass

        # Real visitor is left-most on Railway; return first PUBLIC entry.
        for token in parts:
            if _is_public(token):
                return token

    # 3. Fallback single-value headers.
    real_ip = request.META.get("HTTP_X_REAL_IP", "").strip()
    if real_ip and _is_public(real_ip):
        return real_ip

    return None  # no public client found → internal / health check / local


def _allowed_networks():
    nets = []
    for raw in getattr(settings, "PORTAL_ALLOWED_IPS", []):
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            pass  # ignore malformed entries
    return nets


def request_ip_allowed(request):
    """True if this request comes from an approved (or internal/local) IP."""
    nets = _allowed_networks()
    if not nets:
        return True  # nothing configured → fail-open (never lock everyone out)

    ip_str = get_client_ip(request)
    if ip_str is None:
        return True  # internal / health check / local dev

    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private:
        return True
    return any(ip in net for net in nets)


def user_is_ip_restricted(user):
    """Which users are limited to the approved IPs.

    Only the **admin** role is exempt (``is_admin`` is ``role == 'admin' or
    is_superuser``), so an owner can always sign in from anywhere to manage the
    team or fix a lockout. **Everyone else — managers and employees — may sign
    in only from the approved office IPs.** Anonymous visitors are not
    restricted here; the login view enforces the rule the moment a restricted
    user authenticates.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_admin", False):
        return False  # admin role / superuser → unrestricted
    return True


class IPWhitelistMiddleware:
    """Restrict ORDINARY EMPLOYEES to the approved office IP addresses.

    The portal is office-only for staff: an authenticated employee whose public
    IP is not in ``settings.PORTAL_ALLOWED_IPS`` is signed out and shown a
    professional "access restricted" page (HTTP 403) on every URL.

    Admins/superusers are never IP-restricted, and anonymous visitors (the
    login page itself) are untouched — the login view blocks an employee's
    sign-in from an unapproved network so they never get a usable session.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    # Diagnostics endpoint must always be reachable so an admin can read the
    # exact headers Railway sends from any network when debugging the allow-list.
    _EXEMPT_PATHS = ("/accounts/ip-debug/",)

    def __call__(self, request):
        if request.path in self._EXEMPT_PATHS:
            return self.get_response(request)
        user = getattr(request, "user", None)
        if user_is_ip_restricted(user) and not request_ip_allowed(request):
            client_ip = get_client_ip(request)
            logout(request)  # drop the now-unauthorized session cleanly
            html = render_to_string("ip_blocked.html", {"client_ip": client_ip})
            return HttpResponse(html, status=403)
        return self.get_response(request)

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
