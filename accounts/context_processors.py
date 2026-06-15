"""Template context processors for tenant-aware settings."""

from django.utils import timezone

from attendance.schedule import (
    resolve_schedule, is_within_working_hours, working_hours_label,
)


def tenant_settings(request):
    """Expose the current user's tenant schedule flags to every template.

    - ``commission_enabled``: whether the Sales Commission feature is on for
      this tenant (used to hide commission UI for tenants that disabled it).
    - ``enforce_working_hours``: whether attendance actions are restricted to
      the working-hours window for this tenant.
    - ``work_locked``: True when ``enforce_working_hours`` is on AND the current
      moment is outside the allowed window (so the UI can block actions).
    - ``work_hours_label``: human-readable allowed window, e.g.
      "8:55 AM – 6:30 PM, Mon–Sat".
    """
    defaults = {
        'commission_enabled': True,
        'enforce_working_hours': False,
        'work_locked': False,
        'work_hours_label': '',
    }
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return defaults

    try:
        sched = resolve_schedule(user)
        enforce = bool(getattr(sched, 'enforce_working_hours', False))
        return {
            'commission_enabled': sched.commission_enabled,
            'enforce_working_hours': enforce,
            'work_locked': enforce and not is_within_working_hours(timezone.now(), sched),
            'work_hours_label': working_hours_label(sched) if enforce else '',
        }
    except Exception:
        return defaults
