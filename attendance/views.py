import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required, manager_required
from .models import Attendance, AttendanceBreak
from .schedule import (
    is_weekend, get_shift_start, is_late_checkin, net_work_hours,
    get_post_break_status, SHIFT_START, SHIFT_END, BREAKS,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def get_client_ip(request):
    """Return the real client IP, honouring X-Forwarded-For proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # The first address in the list is the originating client
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


# ---------------------------------------------------------------------------
# Check-in / Check-out
# ---------------------------------------------------------------------------

@login_required
@require_POST
def check_in_view(request):
    """
    Handle employee check-in.

    - Fresh check-in: creates a new Attendance record for today.
    - Re-check-in: if the employee already checked OUT today (accidental
      checkout), clears the checkout and resets work_hours so they can
      continue their shift. The original check-in time is preserved.
    - Blocked: if the employee is currently checked in (no checkout yet).
    Marks the record as late if check-in time is after 09:30.
    Returns a JSON response consumed by the frontend via fetch/AJAX.
    """
    today = timezone.localdate()
    now   = timezone.localtime(timezone.now())

    # ── Block weekends ──────────────────────────────────────────────────────
    if is_weekend(today):
        day_name = today.strftime('%A')
        return JsonResponse(
            {'success': False, 'error': f'{day_name} is a holiday. Enjoy your day off!'},
            status=400,
        )

    existing = Attendance.objects.filter(employee=request.user, date=today).first()

    if existing:
        if existing.check_out:
            # Accidental checkout — undo it: clear checkout & reset work_hours,
            # preserving the original check_in time.
            Attendance.objects.filter(pk=existing.pk).update(check_out=None, work_hours=0)
            existing.refresh_from_db()
            ci_local = timezone.localtime(existing.check_in)
            return JsonResponse({
                'success': True,
                'message': 'Checked in again. Checkout has been cleared.',
                'check_in': ci_local.strftime('%H:%M:%S'),
                'time': ci_local.strftime('%I:%M %p'),
                'is_late': existing.is_late,
                'status': existing.get_status_display(),
                'attendance_id': existing.pk,
            })
        else:
            return JsonResponse(
                {'success': False, 'error': 'You are already checked in.'},
                status=400,
            )

    ip_address = get_client_ip(request)
    location   = request.POST.get('location', '').strip()

    # Determine late status using schedule helper (model.save() also does this)
    late = is_late_checkin(now)
    status = 'late' if late else 'present'

    attendance = Attendance.objects.create(
        employee=request.user,
        date=today,
        check_in=now,
        ip_address=ip_address or None,
        location=location,
        status=status,
        is_late=late,
    )

    ci_local = timezone.localtime(attendance.check_in)
    shift_start = get_shift_start(today)
    return JsonResponse({
        'success': True,
        'message': 'Checked in successfully.',
        'check_in': ci_local.strftime('%H:%M:%S'),
        'time': ci_local.strftime('%I:%M %p'),
        'is_late': attendance.is_late,
        'status': attendance.get_status_display(),
        'attendance_id': attendance.pk,
        'shift_start': shift_start.strftime('%I:%M %p') if shift_start else '',
    })


@login_required
@require_POST
def check_out_view(request):
    """
    Handle employee check-out.

    Updates the check_out field of today's Attendance record and recalculates
    work_hours. Returns a JSON response.
    """
    today = timezone.localdate()
    now = timezone.localtime(timezone.now())

    try:
        attendance = Attendance.objects.get(employee=request.user, date=today)
    except Attendance.DoesNotExist:
        return JsonResponse(
            {
                'success': False,
                'message': 'No check-in record found for today. Please check in first.',
            },
            status=400,
        )

    if attendance.check_out:
        return JsonResponse(
            {
                'success': False,
                'message': 'You have already checked out today.',
            },
            status=400,
        )

    if attendance.check_in and now < attendance.check_in:
        return JsonResponse(
            {
                'success': False,
                'message': 'Check-out time cannot be before check-in time.',
            },
            status=400,
        )

    attendance.check_out = now
    # work_hours is recalculated inside Attendance.save() using net_work_hours()
    attendance.save()

    co_local = timezone.localtime(attendance.check_out)
    return JsonResponse({
        'success': True,
        'message': 'Checked out successfully.',
        'check_out': co_local.strftime('%H:%M:%S'),
        'time': co_local.strftime('%I:%M %p'),
        'work_hours': str(attendance.work_hours),
        'attendance_id': attendance.pk,
    })


# ---------------------------------------------------------------------------
# Restart work after break
# ---------------------------------------------------------------------------

@login_required
@require_POST
def restart_work_view(request):
    """Record that the employee manually resumed work after a scheduled break."""
    today     = timezone.localdate()
    now_aware = timezone.now()
    now_local = timezone.localtime(now_aware)

    attendance = Attendance.objects.filter(
        employee=request.user, date=today
    ).prefetch_related('break_restarts').first()

    if not attendance or not attendance.check_in or attendance.check_out:
        return JsonResponse(
            {'success': False, 'error': 'No active check-in found for today.'},
            status=400,
        )

    restarted = set(attendance.break_restarts.values_list('break_number', flat=True))
    post_break = get_post_break_status(now_aware, restarted)

    if not post_break:
        return JsonResponse(
            {'success': False, 'error': 'No pending break restart found.'},
            status=400,
        )

    break_num     = post_break['break_number']
    scheduled_end = BREAKS[break_num - 1][1]   # time object, e.g. time(19, 15)

    AttendanceBreak.objects.create(
        attendance    = attendance,
        break_number  = break_num,
        scheduled_end = scheduled_end,
        resumed_at    = now_aware,
    )

    delay = post_break['minutes_since_end']
    return JsonResponse({
        'success':       True,
        'message':       f'Work resumed after Break {break_num}.',
        'break_number':  break_num,
        'resumed_at':    now_local.strftime('%I:%M %p'),
        'delay_minutes': delay,
    })


# ---------------------------------------------------------------------------
# Day summary API (used by checkout popup)
# ---------------------------------------------------------------------------

@login_required
def day_summary_api(request):
    """Return a JSON summary of the employee's current work-day for the checkout popup."""
    import datetime as _dt
    today     = timezone.localdate()
    now_aware = timezone.now()
    now_local = timezone.localtime(now_aware)

    attendance = (
        Attendance.objects
        .filter(employee=request.user, date=today)
        .prefetch_related('break_restarts')
        .first()
    )

    if not attendance or not attendance.check_in:
        return JsonResponse({'error': 'No check-in found for today.'}, status=400)

    ci_local = timezone.localtime(attendance.check_in)

    # Tentative net work hours if checkout NOW
    tentative_net     = net_work_hours(attendance.check_in, now_aware)
    net_mins          = int(tentative_net * 60)
    raw_mins          = int((now_local - ci_local).total_seconds() / 60)
    break_deducted    = max(0, raw_mins - net_mins)

    # Late minutes
    shift_start = SHIFT_START.get(ci_local.weekday(), _dt.time(14, 0))
    ci_time     = ci_local.time()
    late_mins   = 0
    if ci_time > shift_start:
        s_dt      = _dt.datetime.combine(ci_local.date(), shift_start)
        ci_dt     = _dt.datetime.combine(ci_local.date(), ci_time)
        late_mins = max(0, int((ci_dt - s_dt).total_seconds() / 60))

    # Build break activity list
    restarts_by_num = {
        r.break_number: r for r in attendance.break_restarts.all()
    }
    breaks_data = []
    for idx, (b_start, b_end) in enumerate(BREAKS):
        bn  = idx + 1
        rec = restarts_by_num.get(bn)
        b_dur_min = int(
            (_dt.datetime.combine(today, b_end) - _dt.datetime.combine(today, b_start))
            .total_seconds() / 60
        )
        breaks_data.append({
            'break_number':    bn,
            'scheduled_start': b_start.strftime('%I:%M %p'),
            'scheduled_end':   b_end.strftime('%I:%M %p'),
            'duration_min':    b_dur_min,
            'restarted':       rec is not None,
            'resumed_at':      timezone.localtime(rec.resumed_at).strftime('%I:%M %p') if rec else None,
            'delay_minutes':   rec.delay_minutes if rec else None,
        })

    return JsonResponse({
        'check_in':            ci_local.strftime('%I:%M %p'),
        'is_late':             attendance.is_late,
        'late_minutes':        late_mins,
        'status':              attendance.get_status_display(),
        'breaks':              breaks_data,
        'tentative_checkout':  now_local.strftime('%I:%M %p'),
        'net_mins':            net_mins,
        'raw_mins':            raw_mins,
        'break_deducted_mins': break_deducted,
        'net_hours_display':   f"{net_mins // 60}h {net_mins % 60}m",
    })


# ---------------------------------------------------------------------------
# Employee views
# ---------------------------------------------------------------------------

@login_required
def my_attendance_view(request):
    """
    Display the authenticated employee's attendance history.

    Builds a monthly calendar grid showing status for each day. Supports
    month/year navigation via GET parameters.
    """
    today = timezone.localdate()

    # Month / year selection from query string, default to current month
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    # Clamp to valid range
    year = max(2000, min(year, today.year + 1))

    # All attendance records for the selected month
    records = Attendance.objects.filter(
        employee=request.user,
        date__year=year,
        date__month=month,
    ).order_by('date')

    records_by_date = {r.date: r for r in records}

    # Build calendar grid (list of weeks, each week is a list of day dicts)
    cal = calendar.monthcalendar(year, month)
    calendar_weeks = []
    for week in cal:
        week_days = []
        for day_num in week:
            if day_num == 0:
                week_days.append({'day': None, 'record': None, 'is_today': False})
            else:
                day_date = date(year, month, day_num)
                week_days.append(
                    {
                        'day': day_num,
                        'date': day_date,
                        'record': records_by_date.get(day_date),
                        'is_today': day_date == today,
                        'is_weekend': day_date.weekday() in (5, 6),  # Sat, Sun
                        'is_future': day_date > today,
                    }
                )
        calendar_weeks.append(week_days)

    # Monthly statistics
    total_present = records.filter(status__in=['present', 'late']).count()
    total_late = records.filter(is_late=True).count()
    total_absent = records.filter(status='absent').count()
    total_leave = records.filter(status='leave').count()
    total_half_day = records.filter(status='half_day').count()
    total_work_hours = sum(r.work_hours for r in records if r.work_hours)

    # All-time history (most recent first, paginated if needed)
    all_records = Attendance.objects.filter(employee=request.user).order_by('-date')[:90]

    # Navigation: previous / next month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # Today's attendance record (for check-in / check-out widget)
    today_record = records_by_date.get(today)

    context = {
        'year': year,
        'month': month,
        'month_name': calendar.month_name[month],
        'calendar_weeks': calendar_weeks,
        'records': all_records,
        'today_record': today_record,
        'total_present': total_present,
        'total_late': total_late,
        'total_absent': total_absent,
        'total_leave': total_leave,
        'total_half_day': total_half_day,
        'total_work_hours': round(total_work_hours, 2),
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
        'today': today,
    }
    return render(request, 'attendance/my_attendance.html', context)


@login_required
def attendance_detail_view(request, pk):
    """Show detail for a single attendance record."""
    attendance = get_object_or_404(Attendance, pk=pk)

    # Employees may only view their own records; admins/managers can view any.
    is_privileged = (
        request.user.role in ('admin', 'manager') or request.user.is_superuser
    )
    if attendance.employee != request.user and not is_privileged:
        messages.error(request, 'You do not have permission to view this record.')
        return redirect('attendance:my_attendance')

    context = {'attendance': attendance}
    return render(request, 'attendance/attendance_detail.html', context)


# ---------------------------------------------------------------------------
# Manager / Admin views
# ---------------------------------------------------------------------------

@login_required
def attendance_report_view(request):
    """
    Show attendance report for all employees.

    Access restricted to admins and managers.
    Supports filtering by employee, date range and status.
    """
    if not (request.user.role in ('admin', 'manager') or request.user.is_superuser):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard:dashboard')

    today = timezone.localdate()
    queryset = Attendance.objects.select_related('employee').order_by('-date', 'employee')

    # --- Filters ---
    employee_id = request.GET.get('employee')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status_filter = request.GET.get('status')

    if employee_id:
        queryset = queryset.filter(employee_id=employee_id)

    if date_from:
        try:
            queryset = queryset.filter(date__gte=date_from)
        except (ValueError, TypeError):
            messages.warning(request, 'Invalid start date format. Please use YYYY-MM-DD.')

    if date_to:
        try:
            queryset = queryset.filter(date__lte=date_to)
        except (ValueError, TypeError):
            messages.warning(request, 'Invalid end date format. Please use YYYY-MM-DD.')

    if status_filter:
        queryset = queryset.filter(status=status_filter)

    # Default: show current month when no date range is given
    if not date_from and not date_to:
        queryset = queryset.filter(date__year=today.year, date__month=today.month)

    employees = User.objects.filter(is_active=True).order_by('first_name', 'last_name')

    # Summary stats for the filtered set
    total_records = queryset.count()
    total_present = queryset.filter(status__in=['present', 'late']).count()
    total_absent = queryset.filter(status='absent').count()
    total_late = queryset.filter(is_late=True).count()

    context = {
        'attendances': queryset[:500],  # cap to avoid huge pages
        'employees': employees,
        'status_choices': Attendance.STATUS_CHOICES,
        'selected_employee': employee_id,
        'date_from': date_from or today.replace(day=1).isoformat(),
        'date_to': date_to or today.isoformat(),
        'selected_status': status_filter,
        'total_records': total_records,
        'total_present': total_present,
        'total_absent': total_absent,
        'total_late': total_late,
        'today': today,
    }
    return render(request, 'attendance/attendance_report.html', context)


@login_required
def mark_absent_view(request, pk=None):
    """
    Allow admins to manually mark an employee as absent for a given date.

    GET  – render the form.
    POST – create or update the Attendance record with status='absent'.
    """
    if not (request.user.role == 'admin' or request.user.is_superuser):
        messages.error(request, 'Only administrators can manually mark absences.')
        return redirect('attendance:attendance_report')

    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        absence_date_str = request.POST.get('date')
        notes = request.POST.get('notes', '').strip()

        # Validate inputs
        if not employee_id or not absence_date_str:
            messages.error(request, 'Employee and date are required.')
            return redirect('attendance:mark_absent')

        try:
            employee = User.objects.get(pk=employee_id, is_active=True)
        except User.DoesNotExist:
            messages.error(request, 'Employee not found.')
            return redirect('attendance:mark_absent')

        try:
            from datetime import datetime
            absence_date = datetime.strptime(absence_date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Invalid date format. Please use YYYY-MM-DD.')
            return redirect('attendance:mark_absent')

        attendance, created = Attendance.objects.update_or_create(
            employee=employee,
            date=absence_date,
            defaults={
                'status': 'absent',
                'check_in': None,
                'check_out': None,
                'work_hours': Decimal('0.00'),
                'notes': notes,
                'ip_address': None,
            },
        )

        action = 'marked' if created else 'updated'
        messages.success(
            request,
            f'{employee.get_full_name() or employee.username} has been {action} '
            f'as absent for {absence_date}.',
        )
        return redirect('attendance:attendance_report')

    # GET – render the form
    employees = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
    context = {
        'employees': employees,
        'today': timezone.localdate(),
    }
    return render(request, 'attendance/mark_absent.html', context)


@login_required
def manage_attendance_view(request, pk=None):
    """
    Admin attendance correction tool.

    Lets an administrator add or fix an attendance record when an employee
    forgot to check in / check out, or when a status needs adjusting.

    GET  – render the form (prefilled when editing an existing record, or
           prefilled from ?employee= & ?date= query params when adding).
    POST – create or update the Attendance record.
    """
    if not (request.user.role == 'admin' or request.user.is_superuser):
        messages.error(request, 'Only administrators can correct attendance records.')
        return redirect('attendance:attendance_report')

    from datetime import datetime

    record = None
    if pk:
        record = get_object_or_404(Attendance.objects.select_related('employee'), pk=pk)

    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        date_str = request.POST.get('date')
        status = request.POST.get('status', 'present')
        check_in_str = request.POST.get('check_in', '').strip()    # "HH:MM"
        check_out_str = request.POST.get('check_out', '').strip()   # "HH:MM"
        notes = request.POST.get('notes', '').strip()

        # --- Validate required inputs ---
        if not employee_id or not date_str:
            messages.error(request, 'Employee and date are required.')
            return redirect(request.path)

        try:
            employee = User.objects.get(pk=employee_id, is_active=True)
        except User.DoesNotExist:
            messages.error(request, 'Employee not found.')
            return redirect(request.path)

        try:
            rec_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Invalid date format. Please use YYYY-MM-DD.')
            return redirect(request.path)

        valid_statuses = {key for key, _ in Attendance.STATUS_CHOICES}
        if status not in valid_statuses:
            messages.error(request, 'Invalid status selected.')
            return redirect(request.path)

        # --- Build timezone-aware check in / out datetimes ---
        tz = timezone.get_current_timezone()
        check_in_dt = None
        check_out_dt = None

        def _make_dt(time_str):
            t = datetime.strptime(time_str, '%H:%M').time()
            naive = datetime.combine(rec_date, t)
            return timezone.make_aware(naive, tz)

        try:
            if check_in_str:
                check_in_dt = _make_dt(check_in_str)
            if check_out_str:
                check_out_dt = _make_dt(check_out_str)
        except ValueError:
            messages.error(request, 'Invalid time format. Please use HH:MM (24-hour).')
            return redirect(request.path)

        if check_out_dt and not check_in_dt:
            messages.error(request, 'Cannot set a check-out time without a check-in time.')
            return redirect(request.path)

        if check_in_dt and check_out_dt and check_out_dt <= check_in_dt:
            messages.error(request, 'Check-out time must be after the check-in time.')
            return redirect(request.path)

        # For non-working statuses, ignore any times
        if status in ('absent', 'leave', 'holiday'):
            check_in_dt = None
            check_out_dt = None

        # --- Create or update ---
        # NOTE: we deliberately avoid Attendance.objects.update_or_create here.
        # On an update it calls save(update_fields=<only the defaults keys>),
        # which would prevent the model's save() from persisting the freshly
        # recomputed work_hours / is_late. A plain full save() recomputes and
        # stores everything correctly.
        attendance = Attendance.objects.filter(employee=employee, date=rec_date).first()
        created = attendance is None
        if created:
            attendance = Attendance(employee=employee, date=rec_date)

        attendance.status = status
        attendance.check_in = check_in_dt
        attendance.check_out = check_out_dt
        attendance.notes = notes

        # Without a complete check-in + check-out pair there are no hours to
        # compute, so reset them (model.save() only recomputes when both exist).
        if not (check_in_dt and check_out_dt):
            attendance.work_hours = Decimal('0.00')
        if check_in_dt is None:
            attendance.is_late = False

        attendance.save()  # full save → recomputes work_hours / is_late / status

        # Attendance.save() forces status to present/late whenever a check-in
        # exists. Honour an explicit half_day choice that still has times.
        if status == 'half_day':
            Attendance.objects.filter(pk=attendance.pk).update(status='half_day')

        action = 'created' if created else 'updated'
        messages.success(
            request,
            f"Attendance for {employee.get_full_name() or employee.username} "
            f"on {rec_date} has been {action}.",
        )
        return redirect('attendance:attendance_report')

    # --- GET: render the form ---
    employees = User.objects.filter(is_active=True).order_by('first_name', 'last_name')

    # Prefill values (editing an existing record, or query-param hints when adding)
    if record:
        prefill_employee = str(record.employee_id)
        prefill_date = record.date.isoformat()
        prefill_status = record.status
        prefill_check_in = timezone.localtime(record.check_in).strftime('%H:%M') if record.check_in else ''
        prefill_check_out = timezone.localtime(record.check_out).strftime('%H:%M') if record.check_out else ''
        prefill_notes = record.notes
    else:
        prefill_employee = request.GET.get('employee', '')
        prefill_date = request.GET.get('date', timezone.localdate().isoformat())
        prefill_status = 'present'
        prefill_check_in = ''
        prefill_check_out = ''
        prefill_notes = ''

    context = {
        'record': record,
        'employees': employees,
        'status_choices': Attendance.STATUS_CHOICES,
        'today': timezone.localdate(),
        'prefill_employee': prefill_employee,
        'prefill_date': prefill_date,
        'prefill_status': prefill_status,
        'prefill_check_in': prefill_check_in,
        'prefill_check_out': prefill_check_out,
        'prefill_notes': prefill_notes,
    }
    return render(request, 'attendance/manage_attendance.html', context)
