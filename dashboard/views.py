from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from attendance.models import Attendance
from leaves.models import LeaveApplication, LeaveBalance
from salary.models import SalaryDeduction, Payslip, SalesCommission, SalaryBonus
from performance.models import PerformanceReview
from holidays.models import Holiday, Announcement
from notifications_app.models import Notification
from accounts.models import CustomUser, Department
from attendance.schedule import (
    get_break_status, get_post_break_status, resolve_schedule,
    display_shift_line, display_breaks_line,
)
from salary.deductions import month_deduction_summary
from decimal import Decimal
import datetime


@login_required
def dashboard_view(request):
    today = timezone.now().date()
    user = request.user

    if user.is_admin or user.is_superuser:
        return redirect('dashboard:admin_dashboard')

    today_attendance = Attendance.objects.filter(employee=user, date=today).first()

    # Detect break / post-break state (only when actively checked in)
    _checked_in_active = (
        today_attendance and
        today_attendance.check_in and
        not today_attendance.check_out
    )
    # Breaks already resumed early today (so they no longer show as "on break").
    restarted_breaks = set()
    if _checked_in_active:
        restarted_breaks = set(
            today_attendance.break_restarts.values_list('break_number', flat=True)
        )
    _sched = resolve_schedule(user)
    break_info = (
        get_break_status(restarted_break_numbers=restarted_breaks, sched=_sched)
        if _checked_in_active else None
    )

    # Detect if a break just ended and employee hasn't restarted yet
    post_break_info = (
        get_post_break_status(restarted_break_numbers=restarted_breaks, sched=_sched)
        if _checked_in_active and not break_info
        else None
    )

    current_year = today.year
    leave_balances = []   # no quota system — shown separately
    pending_leaves = LeaveApplication.objects.filter(employee=user, status='pending').count()
    # Approved paid-leave days this year
    approved_leaves_this_year = sum(
        a.total_days for a in LeaveApplication.objects.filter(
            employee=user, status='approved', from_date__year=current_year
        )
    )
    # Manual deductions the admin entered by hand (stored rows).
    manual_deductions = SalaryDeduction.objects.filter(
        employee=user, month=today.month, year=today.year, source='manual'
    ).order_by('-date')
    manual_deductions_total = sum((d.amount for d in manual_deductions), Decimal('0.00'))

    # Attendance deductions computed LIVE from actual attendance so the figure
    # updates day-by-day (late / early-out / break overstay).
    attendance_summary = month_deduction_summary(user, today.year, today.month)
    auto_deductions_total = attendance_summary['total']

    # Unified list (manual + live attendance) so the card total matches.
    deduction_rows = []
    for d in manual_deductions:
        deduction_rows.append({
            'date': d.date,
            'reason': d.get_reason_display(),
            'amount': d.amount,
            'description': d.description,
            'auto': False,
        })
    for it in attendance_summary['items']:
        deduction_rows.append({
            'date': it['date'],
            'reason': it['reason'].replace('_', ' ').title(),
            'amount': it['amount'],
            'description': it['description'],
            'auto': True,
        })
    deduction_rows.sort(key=lambda r: r['date'], reverse=True)

    total_deductions = manual_deductions_total + auto_deductions_total

    # Base salary remaining after the deductions accrued so far this month.
    basic_salary = Decimal(user.basic_salary or 0)
    remaining_base = basic_salary - total_deductions
    if remaining_base < Decimal('0.00'):
        remaining_base = Decimal('0.00')

    # Sales commissions this month — each record is one sale.
    current_month_commissions = SalesCommission.objects.filter(
        employee=user, month=today.month, year=today.year
    ).order_by('-paid_at')
    commission_total = sum(c.amount for c in current_month_commissions)
    sales_count = current_month_commissions.count()

    # Bonuses / allowances added this month.
    current_month_bonuses = SalaryBonus.objects.filter(
        employee=user, month=today.month, year=today.year
    ).order_by('-date')
    bonuses_total = sum((b.amount for b in current_month_bonuses), Decimal('0.00'))

    # Grand total payable at month end:
    #   (base salary - deductions) + commissions + bonuses
    net_payable = remaining_base + Decimal(commission_total) + bonuses_total

    latest_payslip = Payslip.objects.filter(employee=user).first()
    latest_review = PerformanceReview.objects.filter(employee=user).first()
    upcoming_holidays = Holiday.objects.filter(
        date__gte=today, date__lte=today + datetime.timedelta(days=30)
    ).order_by('date')[:5]
    announcements = Announcement.objects.filter(is_active=True).order_by('-posted_on')[:5]
    notifications = Notification.objects.filter(recipient=user, is_read=False)[:5]
    month_start = today.replace(day=1)
    monthly_attendance = Attendance.objects.filter(employee=user, date__gte=month_start, date__lte=today)
    present_days = monthly_attendance.filter(status__in=['present', 'late']).count()
    absent_days = monthly_attendance.filter(status='absent').count()
    late_days = monthly_attendance.filter(status='late').count()
    show_birthday = bool(
        user.date_of_birth and user.date_of_birth.month == today.month and user.date_of_birth.day == today.day
    )
    show_anniversary = bool(
        user.joining_date and user.joining_date.month == today.month
        and user.joining_date.day == today.day and user.joining_date.year != today.year
    )
    estimated_salary = float(latest_payslip.net_salary) if latest_payslip else (
        float(user.basic_salary or 0) * 1.15 - float(total_deductions)
    )

    context = {
        'today': today,
        'today_attendance': today_attendance,
        'break_info': break_info,
        'post_break_info': post_break_info,
        'leave_balances': leave_balances,
        'approved_leaves_this_year': approved_leaves_this_year,
        'pending_leaves': pending_leaves,
        'current_month_deductions': deduction_rows,
        'deduction_rows': deduction_rows,
        'total_deductions': total_deductions,
        'manual_deductions_total': manual_deductions_total,
        'auto_deductions_total': auto_deductions_total,
        'basic_salary': basic_salary,
        'remaining_base': remaining_base,
        'current_month_commissions': current_month_commissions,
        'commission_total': commission_total,
        'sales_count': sales_count,
        'current_month_bonuses': current_month_bonuses,
        'bonuses_total': bonuses_total,
        'net_payable': net_payable,
        'latest_payslip': latest_payslip,
        'latest_review': latest_review,
        'upcoming_holidays': upcoming_holidays,
        'announcements': announcements,
        'notifications': notifications,
        'present_days': present_days,
        'absent_days': absent_days,
        'late_days': late_days,
        'show_birthday': show_birthday,
        'show_anniversary': show_anniversary,
        'estimated_salary': estimated_salary,
        # Tenant-aware shift card text (Portal A renders the original strings).
        'shift_line': display_shift_line(_sched, today),
        'breaks_line': display_breaks_line(_sched),
    }
    return render(request, 'dashboard/dashboard.html', context)


@login_required
def admin_dashboard_view(request):
    if not (request.user.is_admin or request.user.is_superuser or request.user.is_manager_role):
        return redirect('dashboard:dashboard')

    from accounts.tenancy import scoped_user_qs
    tenant_users = scoped_user_qs(request.user)

    today = timezone.now().date()
    total_employees = tenant_users.filter(is_active=True, role__in=['employee', 'manager']).count()
    total_departments = Department.objects.count()
    present_today = Attendance.objects.filter(date=today, status__in=['present', 'late'], employee__in=tenant_users).count()
    pending_leaves_count = LeaveApplication.objects.filter(status='pending', employee__in=tenant_users).count()
    departments = Department.objects.all()
    dept_data = [{'name': d.name, 'count': tenant_users.filter(department=d, is_active=True).count()} for d in departments]

    # Today's check-in stats — a fresh graph every day. One bar per employee
    # who has checked in today, plotted by their check-in time (decimal hour),
    # coloured green (on time) or red (late).
    checkin_today = (
        Attendance.objects.filter(date=today, check_in__isnull=False, employee__in=tenant_users)
        .select_related('employee')
        .order_by('check_in')
    )
    checkin_data = []
    for a in checkin_today:
        lt = timezone.localtime(a.check_in)
        checkin_data.append({
            'name': a.employee.get_full_name() or a.employee.username,
            'time': lt.strftime('%I:%M %p').lstrip('0'),
            'hour': round(lt.hour + lt.minute / 60.0, 4),
            'is_late': bool(a.is_late),
        })

    recent_employees = tenant_users.filter(role__in=['employee', 'manager']).order_by('-date_joined')[:5]
    todays_attendance = Attendance.objects.filter(date=today, employee__in=tenant_users).select_related('employee').order_by('-check_in')[:10]
    recent_leaves = LeaveApplication.objects.filter(
        status='pending', employee__in=tenant_users
    ).select_related('employee', 'leave_type').order_by('-applied_on')[:8]
    month_start = today.replace(day=1)
    monthly_stats = Attendance.objects.filter(date__gte=month_start, date__lte=today, employee__in=tenant_users)
    month_present = monthly_stats.filter(status__in=['present', 'late']).count()
    month_absent = monthly_stats.filter(status='absent').count()
    month_late = monthly_stats.filter(status='late').count()

    context = {
        'total_employees': total_employees,
        'total_departments': total_departments,
        'present_today': present_today,
        'pending_leaves_count': pending_leaves_count,
        'dept_data': dept_data,
        'checkin_data': checkin_data,
        'recent_employees': recent_employees,
        'todays_attendance': todays_attendance,
        'recent_leaves': recent_leaves,
        'today': today,
        'month_present': month_present,
        'month_absent': month_absent,
        'month_late': month_late,
    }
    return render(request, 'dashboard/admin_dashboard.html', context)


