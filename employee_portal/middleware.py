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


# ---------------------------------------------------------------------------
# Device lock helpers (one registered device per account)
# ---------------------------------------------------------------------------

DEVICE_COOKIE_NAME = "portal_device_id"
DEVICE_COOKIE_MAX_AGE = 10 * 365 * 24 * 3600  # ~10 years ("lifetime")


def user_is_device_locked(user):
    """Which users are bound to a single registered device.

    Same policy as the IP allow-list: only the **admin** role / superuser is
    exempt (so the owner can manage the team from any laptop). Managers and
    employees are each locked to the first device they sign in from.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_admin", False):
        return False
    return True


def ua_signature(ua):
    """Coarse, version-tolerant fingerprint of a User-Agent → 'browser|os'.

    Browser auto-updates change the version number but NOT this signature, so a
    legitimate user is never locked out when their browser updates. Switching
    browser or machine DOES change it — which is exactly the copied-cookie case
    we want to catch. Returns '' if nothing recognisable.
    """
    if not ua:
        return ""
    u = ua.lower()
    if "windows" in u:
        os_ = "windows"
    elif "cros" in u:
        os_ = "chromeos"
    elif "mac os" in u or "macintosh" in u:
        os_ = "mac"
    elif "linux" in u or "x11" in u:
        os_ = "linux"
    else:
        os_ = "other"
    # Order matters: Edge/Opera/Brave also contain "Chrome".
    if "edg" in u:
        br = "edge"
    elif "opr" in u or "opera" in u:
        br = "opera"
    elif "firefox" in u or "fxios" in u:
        br = "firefox"
    elif "chrome" in u or "crios" in u or "chromium" in u:
        br = "chrome"
    elif "safari" in u:
        br = "safari"
    else:
        br = "other"
    return f"{br}|{os_}"


def notify_admins(title, message, link="", throttle_minutes=30):
    """Send a security notification to every active admin/superuser.

    Identical (title+message) alerts are throttled per-admin within
    ``throttle_minutes`` so a retrying attacker can't flood the bell.
    """
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from accounts.models import CustomUser
    from notifications_app.models import Notification

    admins = list(
        CustomUser.objects.filter(is_active=True)
        .filter(Q(role="admin") | Q(is_superuser=True))
        .distinct()
    )
    if not admins:
        return
    cutoff = timezone.now() - timedelta(minutes=throttle_minutes)
    for admin in admins:
        recent = Notification.objects.filter(
            recipient=admin, title=title, message=message, created_at__gte=cutoff
        ).exists()
        if recent:
            continue
        Notification.send(admin, title, message, notification_type="general", link=link)


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

class DeviceLockMiddleware:
    """Bind each non-admin account to ONE device and enforce it on EVERY request.

    This is the real guarantee (the login view only checks at sign-in time):

    * First authenticated request from an account with no registered device
      binds the **current** device (a long-lived cookie token) to that account
      for life — so an employee's own laptop self-registers the moment they
      browse, with no admin action.
    * Every later request from a device whose cookie token does NOT match the
      registered one is signed out and shown a 403 "registered device" page.
      A borrowed/colleague's laptop therefore cannot use the account at all.

    Admins/superusers are exempt so the owner can manage from any laptop.
    """

    _EXEMPT_PREFIXES = ("/static/", "/media/")
    # Login/logout stay reachable; ip-debug is a diagnostics endpoint.
    _EXEMPT_PATHS = (
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/ip-debug/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            not user_is_device_locked(user)
            or request.path in self._EXEMPT_PATHS
            or request.path.startswith(self._EXEMPT_PREFIXES)
        ):
            return self.get_response(request)

        import uuid
        from datetime import timedelta

        from django.utils import timezone

        cookie = request.COOKIES.get(DEVICE_COOKIE_NAME)
        cur_ua = request.META.get("HTTP_USER_AGENT", "")
        cur_ip = get_client_ip(request)
        now = timezone.now()

        # No device registered yet → bind THIS device permanently.
        if not user.device_id:
            token = cookie or uuid.uuid4().hex
            user.device_id = token
            user.device_user_agent = cur_ua[:300]
            user.device_registered_at = now
            user.device_last_ip = cur_ip or ""
            user.device_last_seen = now
            user.save(update_fields=[
                "device_id", "device_user_agent", "device_registered_at",
                "device_last_ip", "device_last_seen",
            ])
            response = self.get_response(request)
            self._set_cookie(response, token)
            return response

        # Wrong / missing device cookie → different device → block.
        if not cookie or cookie != user.device_id:
            return self._block(user, request, reason="an unrecognized device")

        # Right cookie but a DIFFERENT browser/OS → the cookie was copied to
        # another browser/machine (version bumps are tolerated by ua_signature).
        if user.device_user_agent and cur_ua:
            if ua_signature(cur_ua) != ua_signature(user.device_user_agent):
                return self._block(user, request, reason="an unrecognized browser")

        # Legit device + browser. Track IP to spot a copied cookie used from two
        # places at once. We do NOT block on IP change (office NAT can rotate
        # among approved IPs) — we alert the admins instead.
        if cur_ip and user.device_last_ip and cur_ip != user.device_last_ip:
            if user.device_last_seen and (now - user.device_last_seen) < timedelta(minutes=10):
                notify_admins(
                    "Possible session sharing detected",
                    f"{user.get_full_name() or user.username} "
                    f"({user.employee_id or '—'}) was seen from two different IPs "
                    f"({user.device_last_ip} then {cur_ip}) on the same registered "
                    f"device within minutes. This can indicate a copied/shared login.",
                    link=f"/accounts/employees/{user.pk}/",
                )
            user.device_last_ip = cur_ip
            user.device_last_seen = now
            user.save(update_fields=["device_last_ip", "device_last_seen"])
        elif not user.device_last_seen or (now - user.device_last_seen) > timedelta(minutes=5):
            if cur_ip:
                user.device_last_ip = cur_ip
            user.device_last_seen = now
            user.save(update_fields=["device_last_ip", "device_last_seen"])

        response = self.get_response(request)
        self._set_cookie(response, user.device_id)
        return response

    def _set_cookie(self, response, token):
        response.set_cookie(
            DEVICE_COOKIE_NAME,
            token,
            max_age=DEVICE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=not settings.DEBUG,
        )

    def _block(self, user, request, reason):
        notify_admins(
            "Blocked device/browser access attempt",
            f"{user.get_full_name() or user.username} ({user.employee_id or '—'}) "
            f"was blocked trying to use the portal from {reason}. If this was a "
            f"genuine new device, reset their registered device from their profile.",
            link=f"/accounts/employees/{user.pk}/",
        )
        logout(request)
        html = render_to_string("device_blocked.html", {})
        return HttpResponse(html, status=403)


class SingleSessionMiddleware:
    """Allow only ONE active session per non-admin account.

    The latest sign-in wins. ``CustomUser.current_session_key`` records the
    session of the most recent login; any request arriving on a different
    (older) session — a second browser, or a copied/shared login — is signed
    out on its next request. Admins/superusers are exempt.
    """

    _EXEMPT_PREFIXES = ("/static/", "/media/")
    _EXEMPT_PATHS = (
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/ip-debug/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            not user_is_device_locked(user)
            or request.path in self._EXEMPT_PATHS
            or request.path.startswith(self._EXEMPT_PREFIXES)
        ):
            return self.get_response(request)

        registered = getattr(user, "current_session_key", None)
        current = request.session.session_key
        # Only enforce once a login has recorded a key for this account.
        if registered and current and current != registered:
            logout(request)
            messages.info(
                request,
                "You were signed out because this account was signed in on "
                "another device or browser. Only one active session is allowed.",
            )
            return redirect(reverse("accounts:login"))
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
