from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.urls import reverse

from notifications_app.models import Notification
from .decorators import admin_required, manager_required
from .forms import (
    LoginForm,
    EmployeeRegistrationForm,
    EmployeeUpdateForm,
    ProfilePictureForm,
    ChangePasswordForm,
)
from .models import CustomUser, Department


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_employee_id():
    """
    Auto-generate the next employee ID in the format EMP001, EMP002, …
    Finds the highest existing numeric suffix and increments by one.
    """
    existing = (
        CustomUser.objects
        .filter(employee_id__startswith='EMP')
        .exclude(employee_id__isnull=True)
        .values_list('employee_id', flat=True)
    )
    max_num = 0
    for emp_id in existing:
        try:
            num = int(emp_id.replace('EMP', ''))
            if num > max_num:
                max_num = num
        except (ValueError, AttributeError):
            continue
    return f'EMP{max_num + 1:03d}'


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:dashboard')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.cleaned_data['user']

        # Only the admin role may sign in from anywhere. Everyone else
        # (managers and employees) is limited to the approved office network.
        from employee_portal.middleware import (
            user_is_ip_restricted, request_ip_allowed, get_client_ip,
        )
        if user_is_ip_restricted(user) and not request_ip_allowed(request):
            ip = get_client_ip(request) or 'unknown'
            messages.error(
                request,
                f'Access denied: this account can only sign in from an approved '
                f'office network. Your IP ({ip}) is not authorized. Please '
                f'contact your administrator.'
            )
            return render(request, 'accounts/login.html', {'form': form})

        login(request, user)
        messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
        next_url = request.GET.get('next', 'dashboard:dashboard')
        return redirect(next_url)

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('accounts:login')


def ip_debug_view(request):
    """Diagnostics: show exactly what the portal sees for the caller's IP.

    Exempt from the IP allow-list (see IPWhitelistMiddleware._EXEMPT_PATHS) so
    it is reachable from any network. Open this from an approved network AND
    from a blocked one to compare the raw proxy headers and the computed IP.
    """
    from django.http import JsonResponse
    from django.conf import settings
    from employee_portal.middleware import get_client_ip, request_ip_allowed

    data = {
        'computed_client_ip': get_client_ip(request),
        'request_ip_allowed': request_ip_allowed(request),
        'allowed_ips_configured': list(getattr(settings, 'PORTAL_ALLOWED_IPS', [])),
        'xff_index_setting': getattr(settings, 'PORTAL_IP_XFF_INDEX', None),
        'headers': {
            'X-Forwarded-For': request.META.get('HTTP_X_FORWARDED_FOR'),
            'X-Envoy-External-Address': request.META.get('HTTP_X_ENVOY_EXTERNAL_ADDRESS'),
            'X-Real-IP': request.META.get('HTTP_X_REAL_IP'),
            'REMOTE_ADDR': request.META.get('REMOTE_ADDR'),
        },
    }
    return JsonResponse(data, json_dumps_params={'indent': 2})


# ---------------------------------------------------------------------------
# Profile (own account)
# ---------------------------------------------------------------------------

@login_required
def profile_view(request):
    picture_form = ProfilePictureForm(instance=request.user)

    if request.method == 'POST':
        picture_form = ProfilePictureForm(request.POST, request.FILES, instance=request.user)
        if picture_form.is_valid():
            picture_form.save()
            messages.success(request, 'Profile picture updated successfully.')
            return redirect('accounts:profile')

    context = {
        'employee': request.user,
        'picture_form': picture_form,
    }
    return render(request, 'accounts/profile.html', context)


@login_required
def edit_profile_view(request):
    """
    Employees can edit a limited subset of their own profile.
    The EmployeeUpdateForm is used but non-privileged fields are made
    read-only for regular employees so they cannot change their own role,
    salary, etc.
    """
    user = request.user
    form = EmployeeUpdateForm(request.POST or None, instance=user)

    # Restrict fields for non-admin users
    if not user.is_admin:
        restricted_fields = ['employee_id', 'role', 'department', 'manager', 'basic_salary', 'joining_date']
        for field_name in restricted_fields:
            if field_name in form.fields:
                form.fields[field_name].disabled = True

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your profile has been updated successfully.')
        return redirect('accounts:profile')

    context = {
        'form': form,
        'title': 'Edit Profile',
    }
    return render(request, 'accounts/edit_profile.html', context)


@login_required
def change_password_view(request):
    form = ChangePasswordForm(user=request.user, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        # Keep the user logged in after the password change
        update_session_auth_hash(request, user)
        messages.success(request, 'Your password has been changed successfully.')
        return redirect('accounts:profile')

    context = {
        'form': form,
        'title': 'Change Password',
    }
    return render(request, 'accounts/change_password.html', context)


# ---------------------------------------------------------------------------
# Employee management (admin / manager)
# ---------------------------------------------------------------------------

@login_required
def employee_list_view(request):
    """
    Admins see all employees.
    Managers see employees in their department or direct reports.
    Regular employees are redirected.
    """
    user = request.user
    if not user.is_manager_role:
        messages.error(request, 'You do not have permission to view the employee list.')
        return redirect('dashboard:dashboard')

    search_query = request.GET.get('q', '').strip()
    department_filter = request.GET.get('department', '').strip()
    role_filter = request.GET.get('role', '').strip()

    if user.is_admin:
        employees = CustomUser.objects.all()
    else:
        # Managers see their direct reports and department colleagues
        employees = CustomUser.objects.filter(
            Q(manager=user) | Q(department=user.department)
        ).distinct()

    if search_query:
        employees = employees.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(employee_id__icontains=search_query) |
            Q(designation__icontains=search_query)
        )

    if department_filter:
        employees = employees.filter(department__id=department_filter)

    if role_filter:
        employees = employees.filter(role=role_filter)

    employees = employees.select_related('department', 'manager').order_by('first_name', 'last_name')

    departments = Department.objects.all()
    role_choices = CustomUser.ROLE_CHOICES

    context = {
        'employees': employees,
        'search_query': search_query,
        'departments': departments,
        'role_choices': role_choices,
        'department_filter': department_filter,
        'role_filter': role_filter,
        'total_count': employees.count(),
    }
    return render(request, 'accounts/employee_list.html', context)


@login_required
@admin_required
def employee_create_view(request):
    form = EmployeeRegistrationForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        employee = form.save(commit=False)
        # Auto-generate employee_id if not provided by the admin
        if not employee.employee_id:
            employee.employee_id = _generate_employee_id()
        employee.save()

        # Notify the new employee
        Notification.send(
            recipient=employee,
            title='Welcome to the Employee Portal',
            message=(
                f'Hello {employee.get_full_name() or employee.username}, '
                f'your account has been created successfully. '
                f'Your Employee ID is {employee.employee_id}.'
            ),
            notification_type='general',
            link=reverse('accounts:profile'),
        )

        # Notify all admins about the new hire
        admins = CustomUser.objects.filter(role='admin', is_active=True).exclude(pk=request.user.pk)
        for admin_user in admins:
            Notification.send(
                recipient=admin_user,
                title='New Employee Added',
                message=(
                    f'{request.user.get_full_name() or request.user.username} added a new employee: '
                    f'{employee.get_full_name() or employee.username} ({employee.employee_id}).'
                ),
                notification_type='general',
                link=reverse('accounts:employee_detail', kwargs={'pk': employee.pk}),
            )

        # Notify the assigned manager if any
        if employee.manager and employee.manager != request.user:
            Notification.send(
                recipient=employee.manager,
                title='New Team Member',
                message=(
                    f'{employee.get_full_name() or employee.username} ({employee.employee_id}) '
                    f'has been assigned to you as a direct report.'
                ),
                notification_type='general',
                link=reverse('accounts:employee_detail', kwargs={'pk': employee.pk}),
            )

        messages.success(
            request,
            f'Employee {employee.get_full_name() or employee.username} '
            f'({employee.employee_id}) created successfully.'
        )
        return redirect('accounts:employee_detail', pk=employee.pk)

    context = {
        'form': form,
        'is_edit': False,
        'title': 'Create Employee',
        'next_employee_id': _generate_employee_id(),
    }
    return render(request, 'accounts/employee_form.html', context)


@login_required
def employee_detail_view(request, pk):
    employee = get_object_or_404(CustomUser, pk=pk)
    user = request.user

    # Access control:
    # - Admins can view anyone
    # - Managers can view employees in their department or direct reports
    # - Employees can only view their own profile
    if user.is_admin:
        pass  # full access
    elif user.is_manager_role:
        is_direct_report = employee.manager == user
        same_department = (
            employee.department is not None and
            user.department is not None and
            employee.department == user.department
        )
        if not (is_direct_report or same_department or employee.pk == user.pk):
            messages.error(request, 'You do not have permission to view this employee.')
            return redirect('dashboard:dashboard')
    else:
        if employee.pk != user.pk:
            messages.error(request, 'You can only view your own profile.')
            return redirect('accounts:profile')

    # ------------------------------------------------------------------
    # Salary & compensation report for a chosen period (defaults to now).
    # Period is adjustable via ?m=<month>&y=<year>.
    # ------------------------------------------------------------------
    from decimal import Decimal
    from datetime import date as _date
    from django.utils import timezone as _tz
    from salary.models import SalesCommission, SalaryDeduction, SalaryBonus, Payslip
    from attendance.models import Attendance
    from leaves.models import LeaveBalance
    from salary.deductions import month_deduction_summary

    _now = _tz.now()
    try:
        sal_month = int(request.GET.get('m') or _now.month)
        sal_year = int(request.GET.get('y') or _now.year)
    except (ValueError, TypeError):
        sal_month, sal_year = _now.month, _now.year
    if not (1 <= sal_month <= 12):
        sal_month = _now.month

    basic_salary = employee.basic_salary or Decimal('0.00')

    employee_commissions = SalesCommission.objects.filter(
        employee=employee, month=sal_month, year=sal_year
    ).order_by('-paid_at')
    commission_total = sum((c.amount for c in employee_commissions), Decimal('0.00'))

    # Manual deductions are stored rows the admin entered by hand.
    deductions = SalaryDeduction.objects.filter(
        employee=employee, month=sal_month, year=sal_year, source='manual'
    ).order_by('-date')
    manual_deductions_total = sum((d.amount for d in deductions), Decimal('0.00'))

    # Attendance ("auto") deductions are computed LIVE from the actual
    # attendance records so the figure updates day-by-day as the employee is
    # late / leaves early / overstays a break — even before any payslip is run.
    attendance_summary = month_deduction_summary(employee, sal_year, sal_month)
    auto_deductions_total = attendance_summary['total']

    deductions_total = manual_deductions_total + auto_deductions_total

    bonuses = SalaryBonus.objects.filter(
        employee=employee, month=sal_month, year=sal_year
    ).order_by('-date')
    bonuses_total = sum((b.amount for b in bonuses), Decimal('0.00'))

    gross = basic_salary + bonuses_total + commission_total
    net_salary = gross - deductions_total

    # "Remaining base" = base salary after the deductions accrued so far this
    # month. Shown right on the Base Salary card ("ab itni salary reh gayi").
    remaining_base = basic_salary - deductions_total
    if remaining_base < Decimal('0.00'):
        remaining_base = Decimal('0.00')

    # Today's live deduction (if any) for the daily-basis callout.
    _today = _tz.localdate()
    today_deduction = Decimal('0.00')
    today_deduction_desc = ''
    if sal_month == _today.month and sal_year == _today.year:
        for _it in attendance_summary['items']:
            if _it['date'] == _today:
                today_deduction = _it['amount']
                today_deduction_desc = _it['description']
                break

    existing_payslip = Payslip.objects.filter(
        employee=employee, month=sal_month, year=sal_year
    ).first()

    # Recent attendance & leave balances to make the other tabs functional.
    recent_attendance = Attendance.objects.filter(
        employee=employee
    ).order_by('-date')[:10]
    leave_balances = LeaveBalance.objects.filter(employee=employee).select_related('leave_type')

    # For the period selector dropdowns.
    month_names = [
        (i, _date(2000, i, 1).strftime('%B')) for i in range(1, 13)
    ]
    year_choices = list(range(_now.year - 3, _now.year + 2))

    context = {
        'employee': employee,
        # period
        'sal_month': sal_month,
        'sal_year': sal_year,
        'month_names': month_names,
        'year_choices': year_choices,
        # salary figures
        'basic_salary': basic_salary,
        'employee_commissions': employee_commissions,
        'commission_total': commission_total,
        'commission_sales_count': employee_commissions.count(),
        'deductions': deductions,
        'deductions_total': deductions_total,
        'manual_deductions_total': manual_deductions_total,
        'auto_deductions_total': auto_deductions_total,
        'attendance_summary': attendance_summary,
        'attendance_items': attendance_summary['items'],
        'remaining_base': remaining_base,
        'today_deduction': today_deduction,
        'today_deduction_desc': today_deduction_desc,
        'bonuses': bonuses,
        'bonuses_total': bonuses_total,
        'gross': gross,
        'net_salary': net_salary,
        'existing_payslip': existing_payslip,
        # other tabs
        'recent_attendance': recent_attendance,
        'leave_balances': leave_balances,
        # deduction reason choices for the add/edit form
        'deduction_reasons': SalaryDeduction.REASON_CHOICES,
    }
    return render(request, 'accounts/employee_detail.html', context)


@login_required
@admin_required
def employee_edit_view(request, pk):
    employee = get_object_or_404(CustomUser, pk=pk)
    form = EmployeeUpdateForm(request.POST or None, instance=employee)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(
            request,
            f'Employee {employee.get_full_name() or employee.username} updated successfully.'
        )
        return redirect('accounts:employee_detail', pk=employee.pk)

    context = {
        'form': form,
        'employee': employee,
        'is_edit': True,
        'title': f'Edit Employee – {employee.get_full_name() or employee.username}',
    }
    return render(request, 'accounts/employee_form.html', context)


@login_required
@admin_required
def employee_deactivate_view(request, pk):
    employee = get_object_or_404(CustomUser, pk=pk)

    # Prevent self-deactivation
    if employee.pk == request.user.pk:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('accounts:employee_detail', pk=employee.pk)

    if request.method == 'POST':
        employee.is_active = not employee.is_active
        employee.save(update_fields=['is_active'])

        action = 'activated' if employee.is_active else 'deactivated'
        messages.success(
            request,
            f'Employee {employee.get_full_name() or employee.username} has been {action}.'
        )

        # Notify the employee about their account status change
        Notification.send(
            recipient=employee,
            title=f'Account {action.capitalize()}',
            message=f'Your account has been {action} by an administrator.',
            notification_type='general',
            link=reverse('accounts:profile'),
        )

        return redirect('accounts:employee_detail', pk=employee.pk)

    context = {
        'employee': employee,
    }
    return render(request, 'accounts/employee_confirm_deactivate.html', context)


@login_required
@admin_required
def employee_delete_view(request, pk):
    """
    Permanently delete an employee and ALL of their related data
    (attendance, leaves, payslips, deductions, bonuses, performance
    reviews, KPIs, notifications) via database cascade.

    Guard rails:
      - You cannot delete your own account.
      - Superuser accounts are protected from deletion.
      - Only acts on POST (the UI shows a confirmation modal first).
    """
    employee = get_object_or_404(CustomUser, pk=pk)

    if employee.pk == request.user.pk:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('accounts:employee_list')

    if employee.is_superuser:
        messages.error(request, 'Superuser accounts cannot be deleted.')
        return redirect('accounts:employee_list')

    if request.method == 'POST':
        display_name = employee.get_full_name() or employee.username
        employee_code = employee.employee_id or '—'
        employee.delete()  # cascades to all owned records
        messages.success(
            request,
            f'Employee {display_name} ({employee_code}) and all related data '
            f'have been permanently deleted.'
        )
        return redirect('accounts:employee_list')

    # A direct GET falls back to the employee detail page; the modal handles
    # confirmation in the normal flow.
    return redirect('accounts:employee_detail', pk=employee.pk)


@login_required
@admin_required
def employee_reset_data_view(request, pk):
    """
    Wipe ALL of an employee's records while keeping their account intact:
    attendance (and break logs), leave applications & balances, payslips,
    salary deductions, bonuses & sales commissions, performance reviews,
    KPIs and notifications.

    The employee, their login, profile and salary settings remain — they
    simply start with a clean history.

    Guard rails (same as delete):
      - You cannot reset your own account.
      - Superuser accounts are protected.
      - Only acts on POST (the UI shows a confirmation modal first).
    """
    employee = get_object_or_404(CustomUser, pk=pk)

    if employee.pk == request.user.pk:
        messages.error(request, 'You cannot reset your own account data.')
        return redirect('accounts:employee_list')

    if employee.is_superuser:
        messages.error(request, 'Superuser accounts cannot be reset.')
        return redirect('accounts:employee_list')

    if request.method == 'POST':
        from django.db import transaction

        display_name = employee.get_full_name() or employee.username
        employee_code = employee.employee_id or '—'

        # Each accessor is a reverse relation owned by this employee. Wrapped in
        # a transaction so a reset is all-or-nothing.
        with transaction.atomic():
            employee.attendances.all().delete()       # cascades AttendanceBreak
            employee.leave_applications.all().delete()
            employee.leave_balances.all().delete()
            employee.payslips.all().delete()
            employee.deductions.all().delete()
            employee.bonuses.all().delete()
            employee.commissions.all().delete()      # sales commissions
            employee.performance_reviews.all().delete()
            employee.kpis.all().delete()
            employee.notifications.all().delete()

        messages.success(
            request,
            f"All data for {display_name} ({employee_code}) has been reset. "
            f"The account is intact and now has a clean history."
        )
        return redirect('accounts:employee_list')

    return redirect('accounts:employee_detail', pk=employee.pk)
