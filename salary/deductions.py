"""
Attendance-based salary deduction engine.

Business rules (confirmed with the client):

* An employee's monthly salary is ``user.basic_salary`` (set by the admin when
  the employee is created).

* Working days for a month  = all calendar days MINUS Saturdays & Sundays.
  Company holidays are NOT excluded (only Sat/Sun are treated as off).
      daily_rate  = monthly_salary / working_days_in_month

* Each working day has its own scheduled *paid* hours (shift length minus the
  95 minutes of unpaid breaks). Mon–Thu ≈ 7h25m, Fri ≈ 6h25m.
      per_minute_rate = daily_rate / scheduled_paid_minutes(day)

* Deductions (no grace period — 1 minute counts):
      - Late arrival  : paid minutes between shift start and check-in.
      - Early leaving : paid minutes between check-out and shift end.
      - Break overstay: minutes taken beyond the allowed break windows
                        (captured by the "Restart Work" delay).
      - Absent (no approved leave)        : full day's salary.
      - Unpaid leave (LeaveType.is_paid=0): full day's salary.
      - Paid leave / holiday / weekend    : no deduction.

A single aggregated :class:`SalaryDeduction` row (``source='attendance'``) is
stored per employee per day so every existing salary screen (dashboard,
my-salary, payslip, report, PDF) reflects it automatically.
"""
import calendar
import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from attendance.schedule import (
    SHIFT_START, SHIFT_END, BREAKS, is_weekend, get_shift_start,
)

# Arbitrary anchor date for time-only arithmetic.
_EPOCH = datetime.date(2000, 1, 1)


def _q2(value) -> Decimal:
    """Round a Decimal to 2 places (currency)."""
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _mins(start_t: datetime.time, end_t: datetime.time) -> float:
    """Minutes between two ``time`` objects (end - start), 0 if not positive."""
    delta = (
        datetime.datetime.combine(_EPOCH, end_t)
        - datetime.datetime.combine(_EPOCH, start_t)
    ).total_seconds() / 60.0
    return max(0.0, delta)


def _paid_minutes_in_interval(start_t: datetime.time, end_t: datetime.time) -> float:
    """
    Minutes between start_t and end_t that are *paid* — i.e. excluding any
    scheduled break windows that overlap the interval.
    """
    if end_t <= start_t:
        return 0.0
    total = _mins(start_t, end_t)
    for b_start, b_end in BREAKS:
        ov_s = max(start_t, b_start)
        ov_e = min(end_t, b_end)
        if ov_s < ov_e:
            total -= _mins(ov_s, ov_e)
    return max(0.0, total)


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

def working_days_in_month(year: int, month: int) -> int:
    """Calendar days in the month excluding Saturdays and Sundays."""
    _, ndays = calendar.monthrange(year, month)
    return sum(
        1 for day in range(1, ndays + 1)
        if not is_weekend(datetime.date(year, month, day))
    )


def scheduled_paid_minutes(d) -> float:
    """Paid (worked) minutes scheduled for the given date's shift."""
    start = get_shift_start(d)
    if not start:
        return 0.0
    return _paid_minutes_in_interval(start, SHIFT_END)


def daily_rate(monthly_salary, year: int, month: int) -> Decimal:
    wd = working_days_in_month(year, month)
    if wd <= 0:
        return Decimal('0')
    return Decimal(monthly_salary) / Decimal(wd)


def per_minute_rate(monthly_salary, d) -> Decimal:
    paid_min = scheduled_paid_minutes(d)
    if paid_min <= 0:
        return Decimal('0')
    return daily_rate(monthly_salary, d.year, d.month) / Decimal(str(paid_min))


# ---------------------------------------------------------------------------
# Per-day deduction
# ---------------------------------------------------------------------------

def _empty_result(d, monthly_salary):
    return {
        'date': d,
        'reason': 'other',
        'full_day': False,
        'late_minutes': 0,
        'early_minutes': 0,
        'break_minutes': 0,
        'late_amount': Decimal('0.00'),
        'early_amount': Decimal('0.00'),
        'break_amount': Decimal('0.00'),
        'amount': Decimal('0.00'),
        'daily_rate': _q2(daily_rate(monthly_salary, d.year, d.month)) if not is_weekend(d) else Decimal('0.00'),
        'description': '',
    }


def _leave_is_paid(employee, d) -> bool:
    """True if an approved leave covering ``d`` is paid (or unknown → treat paid)."""
    from leaves.models import LeaveApplication
    la = (
        LeaveApplication.objects
        .filter(employee=employee, status='approved',
                from_date__lte=d, to_date__gte=d)
        .select_related('leave_type')
        .first()
    )
    if la and la.leave_type:
        return bool(la.leave_type.is_paid)
    return True


def deduction_for_attendance(attendance, *, tentative_checkout=None) -> dict:
    """
    Compute the deduction breakdown for one :class:`Attendance` record.

    ``tentative_checkout`` (aware datetime) lets the checkout popup preview the
    deduction as if the employee checked out at that moment, before the record
    is actually saved.
    """
    employee = attendance.employee
    monthly = Decimal(employee.basic_salary or 0)
    d = attendance.date
    result = _empty_result(d, monthly)

    # Weekends are not working days — never deducted.
    if is_weekend(d):
        return result

    status = attendance.status
    dr = daily_rate(monthly, d.year, d.month)

    # ----- Full-day deductions --------------------------------------------
    if status == 'absent':
        result.update(
            reason='absent', full_day=True, amount=_q2(dr),
            description='Absent (no approved leave) — full day deducted.',
        )
        return result

    if status == 'leave':
        if not _leave_is_paid(employee, d):
            result.update(
                reason='unpaid_leave', full_day=True, amount=_q2(dr),
                description='Unpaid leave — full day deducted.',
            )
        return result  # paid leave → no deduction

    # ----- Partial (late / early / break overstay) ------------------------
    if status in ('present', 'late', 'half_day'):
        check_in = attendance.check_in
        check_out = attendance.check_out or tentative_checkout
        if not (check_in and check_out):
            return result  # cannot compute without both ends

        ci_t = timezone.localtime(check_in).time()
        co_t = timezone.localtime(check_out).time()
        start = get_shift_start(d)
        end = SHIFT_END

        late_min = _paid_minutes_in_interval(start, ci_t) if ci_t > start else 0.0
        early_min = _paid_minutes_in_interval(co_t, end) if co_t < end else 0.0

        try:
            break_delay = sum(
                b.delay_minutes for b in attendance.break_restarts.all()
            )
        except Exception:
            break_delay = 0
        break_min = max(0, int(break_delay))

        pmr = per_minute_rate(monthly, d)
        late_amt = pmr * Decimal(str(late_min))
        early_amt = pmr * Decimal(str(early_min))
        break_amt = pmr * Decimal(str(break_min))
        total = late_amt + early_amt + break_amt

        # Never deduct more than a full day for a single day.
        if total > dr:
            total = dr

        parts = []
        if late_min > 0:
            parts.append(f'Late {int(round(late_min))}m (Rs {_q2(late_amt)})')
        if early_min > 0:
            parts.append(f'Early-out {int(round(early_min))}m (Rs {_q2(early_amt)})')
        if break_min > 0:
            parts.append(f'Break overstay {break_min}m (Rs {_q2(break_amt)})')

        reason = 'late' if (late_min > 0 and early_min == 0 and break_min == 0) else 'other'

        result.update(
            reason=reason,
            late_minutes=int(round(late_min)),
            early_minutes=int(round(early_min)),
            break_minutes=break_min,
            late_amount=_q2(late_amt),
            early_amount=_q2(early_amt),
            break_amount=_q2(break_amt),
            amount=_q2(total),
            description=' + '.join(parts),
        )
    return result


# ---------------------------------------------------------------------------
# Persistence + month aggregation
# ---------------------------------------------------------------------------

def sync_attendance_deduction(attendance) -> dict:
    """
    Recompute and persist the auto deduction for ``attendance``'s day.

    Idempotent: removes any prior auto row for that employee/day and recreates
    it only when there is an amount to deduct. Manual admin deductions
    (``source='manual'``) are never touched.
    """
    from .models import SalaryDeduction

    result = deduction_for_attendance(attendance)
    d = attendance.date

    SalaryDeduction.objects.filter(
        employee=attendance.employee, date=d, source='attendance',
    ).delete()

    if result['amount'] > 0:
        SalaryDeduction.objects.create(
            employee=attendance.employee,
            date=d,
            month=d.month,
            year=d.year,
            reason=result['reason'],
            amount=result['amount'],
            description=result['description'] or 'Attendance deduction',
            source='attendance',
        )
    return result


def month_deduction_summary(employee, year: int, month: int) -> dict:
    """Aggregate attendance-based deductions for an employee in a month."""
    from attendance.models import Attendance

    records = (
        Attendance.objects
        .filter(employee=employee, date__year=year, date__month=month)
        .prefetch_related('break_restarts')
        .order_by('date')
    )

    items = []
    total = Decimal('0.00')
    late_min = early_min = break_min = 0
    for att in records:
        r = deduction_for_attendance(att)
        if r['amount'] > 0:
            items.append(r)
            total += r['amount']
            late_min += r['late_minutes']
            early_min += r['early_minutes']
            break_min += r['break_minutes']

    return {
        'items': items,
        'total': _q2(total),
        'total_late_minutes': late_min,
        'total_early_minutes': early_min,
        'total_break_minutes': break_min,
        'working_days': working_days_in_month(year, month),
        'daily_rate': _q2(daily_rate(employee.basic_salary or 0, year, month)),
    }
