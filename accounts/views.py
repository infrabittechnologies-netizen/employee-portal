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
        login(request, user)
        messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
        next_url = request.GET.get('next', 'dashboard:dashboard')
        return redirect(next_url)

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('accounts:login')


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

    # Sales commissions for the current month (shown to admin/manager viewers).
    from decimal import Decimal
    from salary.models import SalesCommission
    from django.utils import timezone as _tz
    _now = _tz.now()
    employee_commissions = SalesCommission.objects.filter(
        employee=employee, month=_now.month, year=_now.year
    ).order_by('-paid_at')
    commission_total = sum((c.amount for c in employee_commissions), Decimal('0.00'))

    context = {
        'employee': employee,
        'employee_commissions': employee_commissions,
        'commission_total': commission_total,
        'commission_sales_count': employee_commissions.count(),
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
