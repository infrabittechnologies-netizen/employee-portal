import re

from django.shortcuts import render

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
