"""
Company work-schedule constants and helpers.

The portal supports PER-TENANT schedules. Each function below accepts an
optional ``sched`` (a :class:`Schedule`) describing one tenant's working hours,
breaks, weekends, etc. When ``sched`` is omitted the module falls back to
:data:`DEFAULT_SCHEDULE` — the original hardcoded company shift — so any tenant
WITHOUT a custom :class:`accounts.TenantSchedule` row behaves exactly as before.

Default shift (DEFAULT_SCHEDULE):
  Mon–Thu  2:00 PM – 11:00 PM  (PKT)
  Friday   3:00 PM – 11:00 PM  (PKT)
  Sat/Sun  Full holiday — no check-in allowed

Default breaks (deducted from work_hours):
  6:00 PM – 7:15 PM   (75 min)
  9:40 PM – 10:00 PM  (20 min)
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

# Arbitrary anchor date for time-only arithmetic.
_ANCHOR = datetime.date(2000, 1, 1)


# ---------------------------------------------------------------------------
# Schedule data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BreakWindow:
    start: datetime.time
    end: datetime.time
    label: str = 'Break'
    # When False the window is free time: it is NOT counted as worked hours,
    # but it never produces a salary deduction (no break-overstay penalty).
    deductible: bool = True


@dataclass(frozen=True)
class Schedule:
    # Per-weekday shift start (Monday=0 … Sunday=6). Missing weekday == off day.
    shift_start: dict
    shift_end: datetime.time
    weekend_days: frozenset
    breaks: tuple  # tuple[BreakWindow, ...]
    early_checkin_minutes: int = 10
    break_early_restart_minutes: int = 5
    auto_logout_after_minutes: int = 10
    shift_names: dict = field(default_factory=dict)
    commission_enabled: bool = True
    # When True, attendance actions are only allowed during the working-hours
    # window (earliest check-in → auto-logout, on working days). Outside that
    # window the portal is view-only. Default False keeps Portal A unchanged.
    enforce_working_hours: bool = False

    @property
    def deductible_breaks(self):
        return tuple(b for b in self.breaks if b.deductible)


# ---------------------------------------------------------------------------
# DEFAULT schedule — exactly the original hardcoded company shift (Portal A).
# ---------------------------------------------------------------------------

# Legacy module-level constants kept for backward-compatibility with code /
# management commands that import them directly.
SHIFT_START = {
    0: datetime.time(14, 0),   # Monday    – 2:00 PM
    1: datetime.time(14, 0),   # Tuesday   – 2:00 PM
    2: datetime.time(14, 0),   # Wednesday – 2:00 PM
    3: datetime.time(14, 0),   # Thursday  – 2:00 PM
    4: datetime.time(15, 0),   # Friday    – 3:00 PM
}
SHIFT_END = datetime.time(23, 0)   # 11:00 PM every working day
WEEKEND_DAYS = {5, 6}              # Saturday=5, Sunday=6
BREAKS = [
    (datetime.time(18,  0), datetime.time(19, 15)),   # 6:00 PM – 7:15 PM  (75 min)
    (datetime.time(21, 40), datetime.time(22,  0)),   # 9:40 PM – 10:00 PM (20 min)
]
TOTAL_BREAK_MINUTES = 95
EARLY_CHECKIN_MINUTES = 10
BREAK_EARLY_RESTART_MINUTES = 5
AUTO_LOGOUT_AFTER_MINUTES = 10
SHIFT_NAMES = {
    0: "Regular Shift",
    1: "Regular Shift",
    2: "Regular Shift",
    3: "Regular Shift",
    4: "Friday Shift",
}

DEFAULT_SCHEDULE = Schedule(
    shift_start=dict(SHIFT_START),
    shift_end=SHIFT_END,
    weekend_days=frozenset(WEEKEND_DAYS),
    breaks=(
        BreakWindow(datetime.time(18, 0), datetime.time(19, 15), 'Break 1', True),
        BreakWindow(datetime.time(21, 40), datetime.time(22, 0), 'Break 2', True),
    ),
    early_checkin_minutes=EARLY_CHECKIN_MINUTES,
    break_early_restart_minutes=BREAK_EARLY_RESTART_MINUTES,
    auto_logout_after_minutes=AUTO_LOGOUT_AFTER_MINUTES,
    shift_names=dict(SHIFT_NAMES),
    commission_enabled=True,
)


# ---------------------------------------------------------------------------
# Tenant schedule resolution
# ---------------------------------------------------------------------------

def _parse_time(value):
    """Accept a ``datetime.time`` or "HH:MM"/"HH:MM:SS" string."""
    if isinstance(value, datetime.time):
        return value
    if isinstance(value, str) and value.strip():
        parts = value.strip().split(':')
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return datetime.time(h, m)
    return None


def _minutes_of(t: datetime.time) -> int:
    return t.hour * 60 + t.minute


def schedule_from_config(cfg) -> Schedule:
    """Build a :class:`Schedule` from an ``accounts.TenantSchedule`` row."""
    work_start = cfg.work_start
    work_end = cfg.work_end
    working = cfg.working_day_set or {0, 1, 2, 3, 4}
    weekend = frozenset(set(range(7)) - working)

    early_min = max(0, _minutes_of(work_start) - _minutes_of(cfg.checkin_open))
    logout_after = max(0, _minutes_of(cfg.checkout_max) - _minutes_of(work_end))

    breaks = []
    for b in (cfg.breaks or []):
        bs = _parse_time(b.get('start'))
        be = _parse_time(b.get('end'))
        if not (bs and be):
            continue
        breaks.append(BreakWindow(
            start=bs, end=be,
            label=b.get('label') or 'Break',
            deductible=bool(b.get('deductible', True)),
        ))

    return Schedule(
        shift_start={wd: work_start for wd in working},
        shift_end=work_end,
        weekend_days=weekend,
        breaks=tuple(breaks),
        early_checkin_minutes=early_min,
        break_early_restart_minutes=int(cfg.break_early_restart_minutes or 5),
        auto_logout_after_minutes=logout_after,
        shift_names={wd: 'Regular Shift' for wd in working},
        commission_enabled=bool(cfg.commission_enabled),
        enforce_working_hours=bool(getattr(cfg, 'enforce_working_hours', False)),
    )


def resolve_schedule(user) -> Schedule:
    """Return the :class:`Schedule` governing ``user``'s tenant.

    Falls back to :data:`DEFAULT_SCHEDULE` for superusers, users with no tenant
    config, or anonymous users.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return DEFAULT_SCHEDULE
    try:
        from accounts.tenancy import tenant_root
        root = tenant_root(user) or user
        cfg = getattr(root, 'tenant_schedule', None)
        if cfg is None:
            # tenant_root may differ from the row owner if relation not cached
            from accounts.models import TenantSchedule
            cfg = TenantSchedule.objects.filter(admin=root).first()
        if cfg is not None:
            return schedule_from_config(cfg)
    except Exception:
        pass
    return DEFAULT_SCHEDULE


def _s(sched) -> Schedule:
    return sched if sched is not None else DEFAULT_SCHEDULE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shift_time(t: datetime.time, minutes: int) -> datetime.time:
    """Return ``t`` shifted by ``minutes`` (may be negative), as a time object."""
    shifted = datetime.datetime.combine(_ANCHOR, t) + datetime.timedelta(minutes=minutes)
    return shifted.time()


def break_restart_opens(b_end: datetime.time, sched=None) -> datetime.time:
    """The time the Restart-Work option opens for a break ending at ``b_end``."""
    return _shift_time(b_end, -_s(sched).break_early_restart_minutes)


def is_weekend(d, sched=None) -> bool:
    """Return True if d (date object or weekday int) is a non-working day."""
    wd = d if isinstance(d, int) else d.weekday()
    return wd in _s(sched).weekend_days


def get_shift_start(d, sched=None):
    """Return the shift start time for a date/weekday, or None on off-days."""
    wd = d if isinstance(d, int) else d.weekday()
    return _s(sched).shift_start.get(wd)


def get_shift_name(d, sched=None) -> str:
    wd = d if isinstance(d, int) else d.weekday()
    return _s(sched).shift_names.get(wd, 'Regular Shift')


def earliest_checkin_time(d, sched=None):
    """Earliest allowed check-in time: shift start minus early-checkin minutes."""
    sched = _s(sched)
    start = get_shift_start(d, sched)
    if not start:
        return None
    opened = datetime.datetime.combine(_ANCHOR, start) - datetime.timedelta(
        minutes=sched.early_checkin_minutes
    )
    return opened.time()


def is_too_early_checkin(check_in_aware, sched=None) -> bool:
    """True if the check-in is earlier than the early-window opening for that day."""
    from django.utils import timezone as dj_tz
    ci_local = dj_tz.localtime(check_in_aware)
    earliest = earliest_checkin_time(ci_local.weekday(), sched)
    return bool(earliest and ci_local.time() < earliest)


def auto_logout_time(sched=None) -> datetime.time:
    """The PKT time at/after which employees are auto-logged-out."""
    sched = _s(sched)
    cutoff = datetime.datetime.combine(_ANCHOR, sched.shift_end) + datetime.timedelta(
        minutes=sched.auto_logout_after_minutes
    )
    return cutoff.time()


def is_past_auto_logout(now_aware=None, sched=None) -> bool:
    """True when the current PKT time is in the after-shift logout window."""
    from django.utils import timezone as dj_tz
    if now_aware is None:
        now_aware = dj_tz.now()
    local_t = dj_tz.localtime(now_aware).time()
    return local_t >= auto_logout_time(sched)


def is_late_checkin(check_in_aware, sched=None) -> bool:
    """True if the check_in datetime is after that day's shift start (PKT)."""
    from django.utils import timezone as dj_tz
    ci_local = dj_tz.localtime(check_in_aware)
    start = get_shift_start(ci_local.weekday(), sched)
    return bool(start and ci_local.time() > start)


def is_within_working_hours(now_aware=None, sched=None) -> bool:
    """True when the current PKT moment is inside the tenant's working-hours
    window — i.e. a working day AND between the earliest allowed check-in time
    and the auto-logout cutoff. Used to gate attendance actions.
    """
    from django.utils import timezone as dj_tz
    sched = _s(sched)
    if now_aware is None:
        now_aware = dj_tz.now()
    local = dj_tz.localtime(now_aware)
    if is_weekend(local.date(), sched):
        return False
    earliest = earliest_checkin_time(local.weekday(), sched)
    if not earliest:
        return False
    return earliest <= local.time() <= auto_logout_time(sched)


_WEEKDAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def working_hours_label(sched=None) -> str:
    """Human-readable allowed-action window, e.g.
    "08:55 AM – 06:30 PM, Mon–Sat". Used in the lock notice."""
    sched = _s(sched)
    working = sorted(set(range(7)) - set(sched.weekend_days))
    if not working:
        return 'closed'
    earliest = earliest_checkin_time(working[0], sched)
    latest = auto_logout_time(sched)
    # Build a compact day range/list (handles contiguous spans like Mon–Sat).
    contiguous = working == list(range(working[0], working[-1] + 1))
    if contiguous and len(working) > 1:
        days = f'{_WEEKDAY_ABBR[working[0]]}–{_WEEKDAY_ABBR[working[-1]]}'
    else:
        days = ', '.join(_WEEKDAY_ABBR[w] for w in working)
    et = earliest.strftime('%I:%M %p').lstrip('0') if earliest else ''
    lt = latest.strftime('%I:%M %p').lstrip('0')
    return f'{et} – {lt}, {days}'


def get_break_status(now_aware=None, restarted_break_numbers=None, sched=None):
    """
    Return a dict describing the current break if PKT time falls within a break
    window, otherwise None.

    Keys include ``label`` and ``deductible`` so the UI can name the break
    (e.g. "Asar Namaz Break") and indicate whether it counts against pay.
    """
    from django.utils import timezone as dj_tz
    sched = _s(sched)
    if now_aware is None:
        now_aware = dj_tz.now()
    if restarted_break_numbers is None:
        restarted_break_numbers = set()

    local_now = dj_tz.localtime(now_aware)
    local_t = local_now.time()

    for idx, bw in enumerate(sched.breaks):
        break_num = idx + 1
        if break_num in restarted_break_numbers:
            continue

        b_start, b_end = bw.start, bw.end
        if b_start <= local_t < b_end:
            anchor = local_now.date()
            start_dt = datetime.datetime.combine(anchor, b_start)
            end_dt = datetime.datetime.combine(anchor, b_end)
            now_dt = datetime.datetime.combine(anchor, local_t)
            restart_opens = break_restart_opens(b_end, sched)

            duration_s = int((end_dt - start_dt).total_seconds())
            elapsed_s = int((now_dt - start_dt).total_seconds())
            remaining_s = max(0, duration_s - elapsed_s)

            return {
                'break_number':          break_num,
                'total_breaks':          len(sched.breaks),
                'label':                 bw.label,
                'deductible':            bw.deductible,
                'start':                 b_start,
                'end':                   b_end,
                'duration_min':          duration_s // 60,
                'elapsed_min':           elapsed_s // 60,
                'remaining_secs':        remaining_s,
                'countdown_total_secs':  duration_s,
                'restart_opens':         restart_opens,
                'early_restart_minutes': sched.break_early_restart_minutes,
                'can_restart_early':     local_t >= restart_opens,
                'progress_pct':          min(100, int(elapsed_s * 100 / duration_s)) if duration_s > 0 else 100,
            }
    return None


def get_post_break_status(now_aware=None, restarted_break_numbers=None, sched=None):
    """Info about a break that has ended but the employee has NOT restarted yet."""
    from django.utils import timezone as dj_tz
    sched = _s(sched)
    if now_aware is None:
        now_aware = dj_tz.now()
    if restarted_break_numbers is None:
        restarted_break_numbers = set()

    local_now = dj_tz.localtime(now_aware)
    local_t = local_now.time()
    breaks = sched.breaks

    for idx, bw in enumerate(breaks):
        break_num = idx + 1
        if break_num in restarted_break_numbers:
            continue

        b_start, b_end = bw.start, bw.end
        restart_opens = break_restart_opens(b_end, sched)
        if local_t < restart_opens:
            continue

        if idx + 1 < len(breaks):
            window_end = breaks[idx + 1].start
        else:
            window_end = sched.shift_end

        if local_t >= window_end:
            continue

        anchor = local_now.date()
        end_dt = datetime.datetime.combine(anchor, b_end)
        now_dt = datetime.datetime.combine(anchor, local_t)
        minutes_since = max(0, int((now_dt - end_dt).total_seconds() / 60))
        early = local_t < b_end

        return {
            'break_number':      break_num,
            'label':             bw.label,
            'deductible':        bw.deductible,
            'break_end':         b_end,
            'minutes_since_end': minutes_since,
            'early':             early,
        }
    return None


def net_work_hours(check_in_aware, check_out_aware, sched=None) -> Decimal:
    """
    Net working hours between check-in and check-out, deducting any break
    windows that overlap the work period.
    """
    if not check_in_aware or not check_out_aware:
        return Decimal('0')

    from django.utils import timezone as dj_tz
    sched = _s(sched)
    ci_local = dj_tz.localtime(check_in_aware)
    co_local = dj_tz.localtime(check_out_aware)

    elapsed_secs = (co_local - ci_local).total_seconds()
    if elapsed_secs <= 0:
        return Decimal('0')

    ci_t = ci_local.time()
    co_t = co_local.time()

    deduction_secs = 0
    anchor = datetime.date.today()
    for bw in sched.breaks:
        overlap_s = max(ci_t, bw.start)
        overlap_e = min(co_t, bw.end)
        if overlap_s < overlap_e:
            deduction_secs += (
                datetime.datetime.combine(anchor, overlap_e) -
                datetime.datetime.combine(anchor, overlap_s)
            ).seconds

    net_secs = max(0, elapsed_secs - deduction_secs)
    return Decimal(str(round(net_secs / 3600, 2)))
