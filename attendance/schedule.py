"""
Company work-schedule constants and helpers.

Shift:
  Mon–Thu  2:00 PM – 11:00 PM  (PKT)
  Friday   3:00 PM – 11:00 PM  (PKT)
  Sat/Sun  Full holiday — no check-in allowed

Breaks (deducted from work_hours):
  6:00 PM – 7:15 PM   (75 min)
  9:40 PM – 10:00 PM  (20 min)
"""

import datetime
from decimal import Decimal

# Shift start times keyed by Python weekday (Monday=0 … Friday=4)
SHIFT_START = {
    0: datetime.time(14, 0),   # Monday    – 2:00 PM
    1: datetime.time(14, 0),   # Tuesday   – 2:00 PM
    2: datetime.time(14, 0),   # Wednesday – 2:00 PM
    3: datetime.time(14, 0),   # Thursday  – 2:00 PM
    4: datetime.time(15, 0),   # Friday    – 3:00 PM
}
SHIFT_END = datetime.time(23, 0)   # 11:00 PM every working day

WEEKEND_DAYS = {5, 6}   # Saturday=5, Sunday=6

BREAKS = [
    (datetime.time(18,  0), datetime.time(19, 15)),   # 6:00 PM – 7:15 PM  (75 min)
    (datetime.time(21, 40), datetime.time(22,  0)),   # 9:40 PM – 10:00 PM (20 min)
]

TOTAL_BREAK_MINUTES = 95   # 75 + 20

# Employees may check in at most this many minutes before their shift starts
# (e.g. a 2:00 PM shift opens check-in at 1:50 PM).
EARLY_CHECKIN_MINUTES = 10

# Employees may resume work (Restart Work) up to this many minutes before a
# break officially ends (e.g. Break 1 ends 7:15 PM → restart opens 7:10 PM).
# Resuming inside this early window counts as on-time (no overstay).
BREAK_EARLY_RESTART_MINUTES = 5

# How long after the shift ends (SHIFT_END) before employees are automatically
# signed out of the portal (e.g. 11:00 PM shift end → auto logout at 11:10 PM).
AUTO_LOGOUT_AFTER_MINUTES = 10

SHIFT_NAMES = {
    0: "Regular Shift",
    1: "Regular Shift",
    2: "Regular Shift",
    3: "Regular Shift",
    4: "Friday Shift",
}


def _shift_time(t: datetime.time, minutes: int) -> datetime.time:
    """Return ``t`` shifted by ``minutes`` (may be negative), as a time object."""
    anchor = datetime.date(2000, 1, 1)
    shifted = datetime.datetime.combine(anchor, t) + datetime.timedelta(minutes=minutes)
    return shifted.time()


def break_restart_opens(b_end: datetime.time) -> datetime.time:
    """The time the Restart-Work option opens for a break ending at ``b_end``
    (``b_end`` − BREAK_EARLY_RESTART_MINUTES)."""
    return _shift_time(b_end, -BREAK_EARLY_RESTART_MINUTES)


def is_weekend(d) -> bool:
    """Return True if d (date object or weekday int) is Saturday or Sunday."""
    wd = d if isinstance(d, int) else d.weekday()
    return wd in WEEKEND_DAYS


def get_shift_start(d) -> datetime.time | None:
    """Return the shift start time for a date/weekday, or None on weekends."""
    wd = d if isinstance(d, int) else d.weekday()
    return SHIFT_START.get(wd)


def earliest_checkin_time(d) -> datetime.time | None:
    """
    Earliest allowed check-in time for a date/weekday: shift start minus
    EARLY_CHECKIN_MINUTES. Returns None on weekends (no shift).
    """
    start = get_shift_start(d)
    if not start:
        return None
    anchor = datetime.date(2000, 1, 1)
    opened = datetime.datetime.combine(anchor, start) - datetime.timedelta(
        minutes=EARLY_CHECKIN_MINUTES
    )
    return opened.time()


def is_too_early_checkin(check_in_aware) -> bool:
    """
    Return True if the timezone-aware check-in is earlier than the early-window
    opening (shift start − EARLY_CHECKIN_MINUTES) for that day, in PKT.
    """
    from django.utils import timezone as dj_tz
    ci_local = dj_tz.localtime(check_in_aware)
    earliest = earliest_checkin_time(ci_local.weekday())
    return bool(earliest and ci_local.time() < earliest)


def auto_logout_time() -> datetime.time:
    """The PKT time at/after which employees are auto-logged-out
    (SHIFT_END + AUTO_LOGOUT_AFTER_MINUTES)."""
    anchor = datetime.date(2000, 1, 1)
    cutoff = datetime.datetime.combine(anchor, SHIFT_END) + datetime.timedelta(
        minutes=AUTO_LOGOUT_AFTER_MINUTES
    )
    return cutoff.time()


def is_past_auto_logout(now_aware=None) -> bool:
    """
    Return True when the current PKT time is inside the after-shift logout
    window: from (SHIFT_END + AUTO_LOGOUT_AFTER_MINUTES) until midnight.
    """
    from django.utils import timezone as dj_tz
    if now_aware is None:
        now_aware = dj_tz.now()
    local_t = dj_tz.localtime(now_aware).time()
    return local_t >= auto_logout_time()


def is_late_checkin(check_in_aware) -> bool:
    """
    Return True if the timezone-aware check_in datetime is after the
    shift start for that day (converted to Asia/Karachi local time).
    """
    from django.utils import timezone as dj_tz
    ci_local = dj_tz.localtime(check_in_aware)
    start = SHIFT_START.get(ci_local.weekday())
    return bool(start and ci_local.time() > start)


def get_break_status(now_aware=None, restarted_break_numbers=None) -> dict | None:
    """
    Return a dict describing the current break if PKT time falls within a break
    window, otherwise return None.

    The break always runs for its FULL duration (b_start … b_end). The early
    restart option simply *becomes available* in the final
    ``BREAK_EARLY_RESTART_MINUTES`` minutes (flag ``can_restart_early``) — it
    does NOT shorten the break or its countdown.

    ``restarted_break_numbers`` – break numbers (1-indexed) the employee has
    already resumed today; such a break is no longer treated as "on break"
    (so resuming early immediately returns them to the working state).

    Keys:
        break_number      – 1 or 2
        total_breaks      – total number of breaks in the shift (2)
        start / end       – time objects
        duration_min      – total break length in minutes
        elapsed_min       – minutes already elapsed
        remaining_secs    – seconds left until the break officially ends
        restart_opens     – time the early-restart option becomes available
        can_restart_early – True during the final early-restart window
        progress_pct      – 0-100 (how much of the break has passed)
    """
    from django.utils import timezone as dj_tz
    if now_aware is None:
        now_aware = dj_tz.now()
    if restarted_break_numbers is None:
        restarted_break_numbers = set()

    local_now = dj_tz.localtime(now_aware)
    local_t   = local_now.time()

    for idx, (b_start, b_end) in enumerate(BREAKS):
        break_num = idx + 1

        # If the employee already resumed this break early, they are no longer
        # on break — fall through to the normal working/checkout state.
        if break_num in restarted_break_numbers:
            continue

        # The break runs for its FULL window — the countdown targets the real
        # break end (b_end), so the displayed/deducted break time is unchanged.
        if b_start <= local_t < b_end:
            anchor        = local_now.date()
            start_dt      = datetime.datetime.combine(anchor, b_start)
            end_dt        = datetime.datetime.combine(anchor, b_end)
            now_dt        = datetime.datetime.combine(anchor, local_t)
            restart_opens = break_restart_opens(b_end)

            duration_s  = int((end_dt - start_dt).total_seconds())
            elapsed_s   = int((now_dt - start_dt).total_seconds())
            remaining_s = max(0, duration_s - elapsed_s)

            return {
                'break_number':          break_num,
                'total_breaks':          len(BREAKS),
                'start':                 b_start,
                'end':                   b_end,
                'duration_min':          duration_s // 60,
                'elapsed_min':           elapsed_s  // 60,
                'remaining_secs':        remaining_s,
                'countdown_total_secs':  duration_s,
                'restart_opens':         restart_opens,
                'early_restart_minutes': BREAK_EARLY_RESTART_MINUTES,
                'can_restart_early':     local_t >= restart_opens,
                'progress_pct':          min(100, int(elapsed_s * 100 / duration_s)) if duration_s > 0 else 100,
            }
    return None


def get_post_break_status(now_aware=None, restarted_break_numbers=None) -> dict | None:
    """
    Return info about a break that has ended but the employee has NOT restarted yet.

    restarted_break_numbers – set/list of break numbers (1-indexed) the employee
                              has already restarted today (from AttendanceBreak records).

    Returns None when:
      - Current time is inside a break (handled by get_break_status)
      - All past breaks have been restarted
      - No break has ended yet
    """
    from django.utils import timezone as dj_tz
    if now_aware is None:
        now_aware = dj_tz.now()
    if restarted_break_numbers is None:
        restarted_break_numbers = set()

    local_now = dj_tz.localtime(now_aware)
    local_t   = local_now.time()

    for idx, (b_start, b_end) in enumerate(BREAKS):
        break_num = idx + 1

        # Skip breaks the employee has already restarted
        if break_num in restarted_break_numbers:
            continue

        # The restart option opens a few minutes BEFORE the break officially
        # ends, so an employee may resume early.
        restart_opens = break_restart_opens(b_end)
        if local_t < restart_opens:
            continue

        # Determine the end of the "waiting" window:
        # Up to the start of the next break, or shift end if this is the last break
        if idx + 1 < len(BREAKS):
            window_end = BREAKS[idx + 1][0]
        else:
            window_end = SHIFT_END

        if local_t >= window_end:
            continue  # past this break's waiting window

        # We are in the restart window — employee hasn't clicked Restart yet.
        anchor         = local_now.date()
        end_dt         = datetime.datetime.combine(anchor, b_end)
        now_dt         = datetime.datetime.combine(anchor, local_t)
        # Negative before the official end (early resume) → clamp to 0 (on time).
        minutes_since  = max(0, int((now_dt - end_dt).total_seconds() / 60))
        early          = local_t < b_end

        return {
            'break_number':      break_num,
            'break_end':         b_end,
            'minutes_since_end': minutes_since,
            'early':             early,
        }

    return None


def net_work_hours(check_in_aware, check_out_aware) -> Decimal:
    """
    Return net working hours (as Decimal) between check-in and check-out,
    deducting any break windows that overlap the work period.
    Both arguments must be timezone-aware datetimes; conversion to PKT
    is done internally via Django's localtime().
    """
    if not check_in_aware or not check_out_aware:
        return Decimal('0')

    from django.utils import timezone as dj_tz
    ci_local = dj_tz.localtime(check_in_aware)
    co_local = dj_tz.localtime(check_out_aware)

    elapsed_secs = (co_local - ci_local).total_seconds()
    if elapsed_secs <= 0:
        return Decimal('0')

    ci_t = ci_local.time()
    co_t = co_local.time()

    deduction_secs = 0
    anchor = datetime.date.today()
    for b_start, b_end in BREAKS:
        overlap_s = max(ci_t, b_start)
        overlap_e = min(co_t, b_end)
        if overlap_s < overlap_e:
            deduction_secs += (
                datetime.datetime.combine(anchor, overlap_e) -
                datetime.datetime.combine(anchor, overlap_s)
            ).seconds

    net_secs = max(0, elapsed_secs - deduction_secs)
    return Decimal(str(round(net_secs / 3600, 2)))
