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

SHIFT_NAMES = {
    0: "Regular Shift",
    1: "Regular Shift",
    2: "Regular Shift",
    3: "Regular Shift",
    4: "Friday Shift",
}


def is_weekend(d) -> bool:
    """Return True if d (date object or weekday int) is Saturday or Sunday."""
    wd = d if isinstance(d, int) else d.weekday()
    return wd in WEEKEND_DAYS


def get_shift_start(d) -> datetime.time | None:
    """Return the shift start time for a date/weekday, or None on weekends."""
    wd = d if isinstance(d, int) else d.weekday()
    return SHIFT_START.get(wd)


def is_late_checkin(check_in_aware) -> bool:
    """
    Return True if the timezone-aware check_in datetime is after the
    shift start for that day (converted to Asia/Karachi local time).
    """
    from django.utils import timezone as dj_tz
    ci_local = dj_tz.localtime(check_in_aware)
    start = SHIFT_START.get(ci_local.weekday())
    return bool(start and ci_local.time() > start)


def get_break_status(now_aware=None) -> dict | None:
    """
    Return a dict describing the current break if PKT time falls within a break
    window, otherwise return None.

    Keys:
        break_number    – 1 or 2
        total_breaks    – total number of breaks in the shift (2)
        start / end     – time objects
        duration_min    – total break length in minutes
        elapsed_min     – minutes already elapsed
        remaining_secs  – seconds left in this break
        progress_pct    – 0-100 (how much of the break has passed)
    """
    from django.utils import timezone as dj_tz
    if now_aware is None:
        now_aware = dj_tz.now()

    local_now = dj_tz.localtime(now_aware)
    local_t   = local_now.time()

    for idx, (b_start, b_end) in enumerate(BREAKS):
        if b_start <= local_t < b_end:
            anchor      = local_now.date()
            start_dt    = datetime.datetime.combine(anchor, b_start)
            end_dt      = datetime.datetime.combine(anchor, b_end)
            now_dt      = datetime.datetime.combine(anchor, local_t)

            duration_s  = int((end_dt  - start_dt).total_seconds())
            elapsed_s   = int((now_dt  - start_dt).total_seconds())
            remaining_s = max(0, duration_s - elapsed_s)

            return {
                'break_number':   idx + 1,
                'total_breaks':   len(BREAKS),
                'start':          b_start,
                'end':            b_end,
                'duration_min':   duration_s  // 60,
                'elapsed_min':    elapsed_s   // 60,
                'remaining_secs': remaining_s,
                'progress_pct':   min(100, int(elapsed_s * 100 / duration_s)),
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

        # Skip if this break hasn't ended yet (or we're inside it)
        if local_t < b_end:
            continue

        # Determine the end of the "waiting" window:
        # Up to the start of the next break, or shift end if this is the last break
        if idx + 1 < len(BREAKS):
            window_end = BREAKS[idx + 1][0]
        else:
            window_end = SHIFT_END

        if local_t >= window_end:
            continue  # past this break's waiting window

        # We are in the restart window — employee hasn't clicked Restart yet
        anchor         = local_now.date()
        end_dt         = datetime.datetime.combine(anchor, b_end)
        now_dt         = datetime.datetime.combine(anchor, local_t)
        minutes_since  = int((now_dt - end_dt).total_seconds() / 60)

        return {
            'break_number':      break_num,
            'break_end':         b_end,
            'minutes_since_end': minutes_since,
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
