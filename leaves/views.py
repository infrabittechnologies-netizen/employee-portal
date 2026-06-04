import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from notifications_app.models import Notification
from .forms import LeaveApplicationForm, LeaveReviewForm, LeaveTypeForm
from .models import LeaveApplication, LeaveBalance, LeaveType

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_working_days(from_date, to_date):
    """
    Return the number of working days (Mon–Fri) between from_date and to_date
    inclusive. Saturday and Sunday are full holidays.
    """
    if from_date > to_date:
        return 0
    total = 0
    current = from_date
    while current <= to_date:
        if current.weekday() not in (5, 6):   # 5=Sat, 6=Sun
            total += 1
        current += timedelta(days=1)
    return total


def _is_manager_or_admin(user):
    return user.role in ('admin', 'manager') or user.is_superuser


# ---------------------------------------------------------------------------
# Employee views
# ---------------------------------------------------------------------------

@login_required
def apply_leave_view(request):
    """
    Let an employee submit a new leave application.

    Validates:
    - No date overlap with existing pending/approved leaves.
    - Sufficient leave balance for the requested type.
    Weekends are excluded from the day count.
    A notification is sent to the employee's manager on successful submission.
    """
    if request.method == 'POST':
        form = LeaveApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            leave_type = form.cleaned_data['leave_type']
            from_date = form.cleaned_data['from_date']
            to_date = form.cleaned_data['to_date']
            is_half_day = form.cleaned_data['is_half_day']

            # --- Overlap check ---
            overlapping = LeaveApplication.objects.filter(
                employee=request.user,
                status__in=['pending', 'approved'],
            ).exclude(
                to_date__lt=from_date
            ).exclude(
                from_date__gt=to_date
            )
            if overlapping.exists():
                messages.error(
                    request,
                    'You already have a pending or approved leave that overlaps '
                    'with the selected dates. Please choose different dates.',
                )
                return render(request, 'leaves/apply_leave.html', {'form': form})

            # --- Calculate working days ---
            if is_half_day:
                total_days = Decimal('0.5')
            else:
                total_days = Decimal(_count_working_days(from_date, to_date))

            # No leave-quota check — any number of paid-leave applications
            # is allowed.  Approval/rejection is the admin's discretion.

            # --- Save the application ---
            application = form.save(commit=False)
            application.employee = request.user
            application.total_days = int(total_days) if not is_half_day else total_days
            application.save()

            # --- Notify manager ---
            manager = getattr(request.user, 'manager', None)
            if manager:
                Notification.send(
                    recipient=manager,
                    title='New Leave Application',
                    message=(
                        f'{request.user.get_full_name() or request.user.username} '
                        f'has applied for {leave_type.name} leave from '
                        f'{from_date} to {to_date} ({total_days} day(s)).'
                    ),
                    notification_type='leave',
                    link=f'/leaves/{application.pk}/review/',
                )

            messages.success(
                request,
                f'Your leave application for {leave_type.name} '
                f'({from_date} – {to_date}) has been submitted successfully.',
            )
            return redirect('leaves:my_leaves')
    else:
        form = LeaveApplicationForm()

    context = {'form': form}
    return render(request, 'leaves/apply_leave.html', context)


@login_required
def my_leaves_view(request):
    """
    Display the authenticated employee's leave history.
    Leave balance/quota is not enforced — all leaves are admin-approved paid leaves.
    """
    current_year = timezone.localdate().year

    applications = LeaveApplication.objects.filter(
        employee=request.user
    ).select_related('leave_type', 'reviewed_by').order_by('-applied_on')

    pending_count  = applications.filter(status='pending').count()
    approved_count = applications.filter(status='approved').count()
    rejected_count = applications.filter(status='rejected').count()

    # Days taken this year (approved leaves only)
    approved_this_year = applications.filter(
        status='approved',
        from_date__year=current_year,
    )
    days_taken_this_year = sum(a.total_days for a in approved_this_year)

    context = {
        'applications': applications,
        'balances': [],               # no quota system
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'days_taken_this_year': days_taken_this_year,
        'current_year': current_year,
    }
    return render(request, 'leaves/my_leaves.html', context)


@login_required
def leave_detail_view(request, pk):
    """Display the full details of a single leave application."""
    application = get_object_or_404(
        LeaveApplication.objects.select_related('employee', 'leave_type', 'reviewed_by'),
        pk=pk,
    )

    # Permission: employees can only see their own applications.
    if application.employee != request.user and not _is_manager_or_admin(request.user):
        messages.error(request, 'You do not have permission to view this application.')
        return redirect('leaves:my_leaves')

    form = LeaveReviewForm(instance=application) if _is_manager_or_admin(request.user) else None
    context = {
        'leave_application': application,
        'form': form,
    }
    return render(request, 'leaves/leave_detail.html', context)


@login_required
def cancel_leave_view(request, pk):
    """
    Allow an employee to cancel their own pending leave application.
    Only applications with status='pending' can be cancelled.
    """
    application = get_object_or_404(LeaveApplication, pk=pk, employee=request.user)

    if application.status != 'pending':
        messages.error(
            request,
            'Only pending leave applications can be cancelled.',
        )
        return redirect('leaves:leave_detail', pk=pk)

    if request.method == 'POST':
        application.status = 'cancelled'
        application.save(update_fields=['status'])
        messages.success(request, 'Your leave application has been cancelled.')
        return redirect('leaves:my_leaves')

    # GET – ask for confirmation
    context = {'application': application}
    return render(request, 'leaves/cancel_leave_confirm.html', context)


# ---------------------------------------------------------------------------
# Manager / Admin views
# ---------------------------------------------------------------------------

@login_required
def pending_leaves_view(request):
    """
    Show all pending leave applications for managers and admins.
    Managers can only see requests from their direct reports by default,
    but admins can see all.
    """
    if not _is_manager_or_admin(request.user):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard:dashboard')

    queryset = LeaveApplication.objects.filter(
        status='pending'
    ).select_related('employee', 'leave_type').order_by('applied_on')

    # Managers only see their subordinates' requests
    if request.user.role == 'manager' and not request.user.is_superuser:
        queryset = queryset.filter(employee__manager=request.user)

    # Optional filters
    leave_type_id = request.GET.get('leave_type')
    employee_id = request.GET.get('employee')

    if leave_type_id:
        queryset = queryset.filter(leave_type_id=leave_type_id)
    if employee_id:
        queryset = queryset.filter(employee_id=employee_id)

    context = {
        'applications': queryset,
        'leave_types': LeaveType.objects.all().order_by('name'),
        'employees': User.objects.filter(is_active=True).order_by('first_name', 'last_name'),
        'selected_leave_type': leave_type_id,
        'selected_employee': employee_id,
        'total_pending': queryset.count(),
    }
    return render(request, 'leaves/pending_leaves.html', context)


@login_required
def review_leave_view(request, pk):
    """
    Allow a manager or admin to approve or reject a leave application.

    On approval:
    - Updates LeaveBalance.used for the current year.
    - Sends a notification to the employee.

    On rejection:
    - Sends a notification to the employee with the reviewer's comment.
    """
    if not _is_manager_or_admin(request.user):
        messages.error(request, 'You do not have permission to review leave applications.')
        return redirect('dashboard:dashboard')

    application = get_object_or_404(
        LeaveApplication.objects.select_related('employee', 'leave_type'),
        pk=pk,
    )

    if application.status != 'pending':
        messages.warning(
            request,
            f'This application has already been {application.get_status_display().lower()}.',
        )
        return redirect('leaves:leave_detail', pk=pk)

    if request.method == 'POST':
        form = LeaveReviewForm(request.POST, instance=application)
        if form.is_valid():
            reviewed_application = form.save(commit=False)
            reviewed_application.reviewed_by = request.user
            reviewed_application.reviewed_on = timezone.now()
            reviewed_application.save()

            new_status = reviewed_application.status
            employee = reviewed_application.employee
            # No leave-balance deduction — approval itself authorises the paid leave.

            # --- Notify the employee ---
            if new_status == 'approved':
                notification_title = 'Leave Application Approved'
                notification_message = (
                    f'Your {reviewed_application.leave_type.name} leave from '
                    f'{reviewed_application.from_date} to {reviewed_application.to_date} '
                    f'has been approved by '
                    f'{request.user.get_full_name() or request.user.username}.'
                )
            else:
                notification_title = 'Leave Application Rejected'
                notification_message = (
                    f'Your {reviewed_application.leave_type.name} leave from '
                    f'{reviewed_application.from_date} to {reviewed_application.to_date} '
                    f'has been rejected by '
                    f'{request.user.get_full_name() or request.user.username}.'
                )
                if reviewed_application.review_comment:
                    notification_message += (
                        f' Reason: {reviewed_application.review_comment}'
                    )

            Notification.send(
                recipient=employee,
                title=notification_title,
                message=notification_message,
                notification_type='leave',
                link=f'/leaves/{reviewed_application.pk}/',
            )

            messages.success(
                request,
                f'Leave application has been {new_status} successfully.',
            )
            return redirect('leaves:pending_leaves')
        # Form errors fall through to re-render below
    else:
        form = LeaveReviewForm(instance=application)

    context = {
        'form': form,
        'application': application,
    }
    return render(request, 'leaves/review_leave.html', context)


@login_required
def leave_calendar_view(request):
    """
    Display a team-wide leave calendar for the selected month.

    Shows approved leaves for all team members visible to the current user.
    """
    today = timezone.localdate()

    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    year = max(2000, min(year, today.year + 1))

    # Determine which employees to show
    if _is_manager_or_admin(request.user):
        employees = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
    else:
        # Regular employee: show themselves + teammates who share the same manager
        if request.user.manager:
            employees = User.objects.filter(
                is_active=True,
                manager=request.user.manager,
            ).order_by('first_name', 'last_name')
        else:
            employees = User.objects.filter(pk=request.user.pk)

    # Approved leaves that overlap with the selected month
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])

    leaves = LeaveApplication.objects.filter(
        status='approved',
        employee__in=employees,
    ).exclude(
        to_date__lt=month_start
    ).exclude(
        from_date__gt=month_end
    ).select_related('employee', 'leave_type').order_by('from_date')

    # Build calendar grid
    cal = calendar.monthcalendar(year, month)
    calendar_weeks = []
    for week in cal:
        week_days = []
        for day_num in week:
            if day_num == 0:
                week_days.append({'day': None, 'leaves': []})
            else:
                day_date = date(year, month, day_num)
                day_leaves = [
                    lv for lv in leaves
                    if lv.from_date <= day_date <= lv.to_date
                ]
                week_days.append(
                    {
                        'day': day_num,
                        'date': day_date,
                        'leaves': day_leaves,
                        'is_today': day_date == today,
                        'is_weekend': day_date.weekday() in (5, 6),
                    }
                )
        calendar_weeks.append(week_days)

    # Navigation
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    context = {
        'year': year,
        'month': month,
        'month_name': calendar.month_name[month],
        'calendar_weeks': calendar_weeks,
        'leaves': leaves,
        'employees': employees,
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
        'today': today,
        'leave_types': LeaveType.objects.all(),
    }
    return render(request, 'leaves/leave_calendar.html', context)


@login_required
def admin_leave_type_view(request):
    """
    Admin-only CRUD view for leave types.

    GET  with ?pk=<id>  – edit an existing leave type.
    POST with pk in form – update an existing leave type.
    GET  without pk     – list all leave types and show create form.
    POST without pk     – create a new leave type.
    DELETE via POST with ?action=delete&pk=<id> – delete a leave type.
    """
    if not (request.user.role == 'admin' or request.user.is_superuser):
        messages.error(request, 'Only administrators can manage leave types.')
        return redirect('dashboard:dashboard')

    # Handle delete action
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        lt_pk = request.POST.get('pk')
        leave_type = get_object_or_404(LeaveType, pk=lt_pk)
        if leave_type.applications.filter(status__in=['pending', 'approved']).exists():
            messages.error(
                request,
                f'Cannot delete "{leave_type.name}" because it has pending or approved applications.',
            )
        else:
            leave_type_name = leave_type.name
            leave_type.delete()
            messages.success(request, f'Leave type "{leave_type_name}" has been deleted.')
        return redirect('leaves:leave_types')

    # Edit mode: load existing instance
    edit_pk = request.GET.get('pk') or request.POST.get('pk')
    instance = None
    if edit_pk:
        instance = get_object_or_404(LeaveType, pk=edit_pk)

    if request.method == 'POST':
        form = LeaveTypeForm(request.POST, instance=instance)
        if form.is_valid():
            saved = form.save()
            if instance:
                messages.success(request, f'Leave type "{saved.name}" updated successfully.')
            else:
                messages.success(request, f'Leave type "{saved.name}" created successfully.')
            return redirect('leaves:leave_types')
    else:
        form = LeaveTypeForm(instance=instance)

    leave_types = LeaveType.objects.all().order_by('name')

    context = {
        'form': form,
        'leave_types': leave_types,
        'editing': instance,
    }
    return render(request, 'leaves/admin_leave_types.html', context)
