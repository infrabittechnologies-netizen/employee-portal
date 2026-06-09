import calendar
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from attendance.models import Attendance
from .forms import BonusForm, DeductionForm, GeneratePayslipForm
from .models import Payslip, SalaryBonus, SalaryDeduction, SalesCommission

User = get_user_model()


# ---------------------------------------------------------------------------
# Employee-facing views
# ---------------------------------------------------------------------------

@login_required
def my_salary_view(request):
    """Show the logged-in employee's payslips and current-month activity."""
    now = timezone.now()
    current_month = now.month
    current_year = now.year

    payslips = Payslip.objects.filter(employee=request.user).order_by('-year', '-month')

    current_deductions = SalaryDeduction.objects.filter(
        employee=request.user,
        month=current_month,
        year=current_year,
    )
    current_bonuses = SalaryBonus.objects.filter(
        employee=request.user,
        month=current_month,
        year=current_year,
    )
    current_commissions = SalesCommission.objects.filter(
        employee=request.user,
        month=current_month,
        year=current_year,
    ).order_by('-paid_at')
    current_commission_total = sum(
        (c.amount for c in current_commissions), Decimal('0.00')
    )

    context = {
        'payslips': payslips,
        'current_deductions': current_deductions,
        'current_bonuses': current_bonuses,
        'current_commissions': current_commissions,
        'current_commission_total': current_commission_total,
        'current_sales_count': current_commissions.count(),
        'current_month': current_month,
        'current_year': current_year,
    }
    return render(request, 'salary/my_salary.html', context)


@login_required
def payslip_detail_view(request, pk):
    """Show a single payslip. Employees can only view their own."""
    payslip = get_object_or_404(Payslip, pk=pk)

    if not request.user.is_admin and payslip.employee != request.user:
        messages.error(request, 'You are not authorised to view this payslip.')
        return redirect('salary:my_salary')

    deductions = SalaryDeduction.objects.filter(
        payslip=payslip,
    )
    bonuses = SalaryBonus.objects.filter(
        payslip=payslip,
    )
    commissions = SalesCommission.objects.filter(
        payslip=payslip,
    )

    # Fall back to month/year match when items are not linked to the payslip yet
    if not deductions.exists():
        deductions = SalaryDeduction.objects.filter(
            employee=payslip.employee,
            month=payslip.month,
            year=payslip.year,
        )
    if not bonuses.exists():
        bonuses = SalaryBonus.objects.filter(
            employee=payslip.employee,
            month=payslip.month,
            year=payslip.year,
        )
    if not commissions.exists():
        commissions = SalesCommission.objects.filter(
            employee=payslip.employee,
            month=payslip.month,
            year=payslip.year,
        )

    commission_total = sum((c.amount for c in commissions), Decimal('0.00'))

    context = {
        'payslip': payslip,
        'deductions': deductions,
        'bonuses': bonuses,
        'commissions': commissions,
        'commission_total': commission_total,
    }
    return render(request, 'salary/payslip_detail.html', context)


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------

@admin_required
def generate_payslip_view(request):
    """Generate or update a payslip for an employee for a given month/year."""
    form = GeneratePayslipForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        employee = form.cleaned_data['employee']
        month = form.cleaned_data['month']
        year = form.cleaned_data['year']

        # Count calendar working days for that month (Mon-Fri)
        _, days_in_month = calendar.monthrange(year, month)
        working_days = sum(
            1
            for d in range(1, days_in_month + 1)
            if calendar.weekday(year, month, d) < 5
        )

        # Count attendance records
        attendance_qs = Attendance.objects.filter(
            employee=employee,
            date__month=month,
            date__year=year,
        )
        present_statuses = {'present', 'late', 'half_day'}
        present_days = attendance_qs.filter(status__in=present_statuses).count()
        absent_days = attendance_qs.filter(status='absent').count()

        basic_salary = employee.basic_salary

        # Sum deductions and bonuses for the period
        total_deductions = SalaryDeduction.objects.filter(
            employee=employee,
            month=month,
            year=year,
        ).values_list('amount', flat=True)
        total_deductions_sum = sum(total_deductions, Decimal('0.00'))

        total_bonuses = SalaryBonus.objects.filter(
            employee=employee,
            month=month,
            year=year,
        ).values_list('amount', flat=True)
        total_bonuses_sum = sum(total_bonuses, Decimal('0.00'))

        # Sales commissions for the period — added into earnings (net salary).
        total_commissions = SalesCommission.objects.filter(
            employee=employee,
            month=month,
            year=year,
        ).values_list('amount', flat=True)
        total_commissions_sum = sum(total_commissions, Decimal('0.00'))

        # Commissions are folded into allowances so they increase net salary.
        total_allowances_sum = total_bonuses_sum + total_commissions_sum

        net_salary = basic_salary + total_allowances_sum - total_deductions_sum

        payslip, created = Payslip.objects.update_or_create(
            employee=employee,
            month=month,
            year=year,
            defaults={
                'basic_salary': basic_salary,
                'total_allowances': total_allowances_sum,
                'total_deductions': total_deductions_sum,
                'net_salary': net_salary,
                'working_days': working_days,
                'present_days': present_days,
                'absent_days': absent_days,
                'processed_by': request.user,
                'generated_on': timezone.now(),
                'status': 'draft',
            },
        )

        # Link orphan deductions/bonuses/commissions to this payslip
        SalaryDeduction.objects.filter(
            employee=employee,
            month=month,
            year=year,
            payslip__isnull=True,
        ).update(payslip=payslip)

        SalaryBonus.objects.filter(
            employee=employee,
            month=month,
            year=year,
            payslip__isnull=True,
        ).update(payslip=payslip)

        SalesCommission.objects.filter(
            employee=employee,
            month=month,
            year=year,
            payslip__isnull=True,
        ).update(payslip=payslip)

        action = 'generated' if created else 'updated'
        messages.success(request, f'Payslip {action} for {employee.get_full_name() or employee.username}.')
        return redirect('salary:payslip_detail', pk=payslip.pk)

    context = {'form': form}
    return render(request, 'salary/generate_payslip.html', context)


@admin_required
def add_deduction_view(request):
    """Add a salary deduction for an employee."""
    form = DeductionForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        deduction = form.save(commit=False)
        deduction.applied_by = request.user
        deduction.save()
        messages.success(request, 'Deduction added successfully.')
        return redirect('salary:salary_report')

    context = {'form': form, 'title': 'Add Deduction'}
    return render(request, 'salary/deduction_form.html', context)


@admin_required
@require_POST
def pay_commission_view(request, pk):
    """Pay a sales commission to an employee.

    Each submission records ONE commission (== one sale) with the exact
    date & time, shows instantly on the employee's dashboard, and is added
    into that month's payslip net salary.
    """
    employee = get_object_or_404(User, pk=pk)

    if employee.is_superuser:
        messages.error(request, 'Cannot pay commission to a superuser account.')
        return redirect('accounts:employee_list')

    raw_amount = (request.POST.get('amount') or '').strip()
    note = (request.POST.get('note') or '').strip()
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        amount = Decimal('0')

    # Where to return after the action: the employees list (default) or the
    # employee's detail/report page.
    back_to_detail = request.POST.get('redirect_to') == 'detail'

    if amount <= 0:
        messages.error(request, 'Please enter a valid commission amount.')
        if back_to_detail:
            return redirect('accounts:employee_detail', pk=employee.pk)
        return redirect('accounts:employee_list')

    now = timezone.now()
    SalesCommission.objects.create(
        employee=employee,
        amount=amount,
        note=note,
        paid_at=now,
        paid_by=request.user,
        month=now.month,
        year=now.year,
    )

    # Keep any existing payslip for that period in sync.
    _recalc_payslip_for(employee, now.month, now.year)

    # Notify the employee so it surfaces immediately in their portal.
    try:
        from notifications_app.models import Notification
        Notification.objects.create(
            recipient=employee,
            title='Sales commission received',
            message=f'You received a commission of PKR {amount:,.2f}'
                    + (f' — {note}' if note else '') + '.',
            link=reverse('dashboard:dashboard'),
        )
    except Exception:
        pass

    display_name = employee.get_full_name() or employee.username
    messages.success(
        request,
        f'Commission of PKR {amount:,.2f} paid to {display_name}. '
        f'1 sale recorded.'
    )
    if back_to_detail:
        return redirect('accounts:employee_detail', pk=employee.pk)
    return redirect('accounts:employee_list')


def _recalc_payslip_for(employee, month, year):
    """If a payslip already exists for this period, recompute its totals so
    edits/removals of commissions (and other items) stay consistent."""
    payslip = Payslip.objects.filter(
        employee=employee, month=month, year=year
    ).first()
    if not payslip:
        return

    total_deductions_sum = sum(
        SalaryDeduction.objects.filter(
            employee=employee, month=month, year=year
        ).values_list('amount', flat=True),
        Decimal('0.00'),
    )
    total_bonuses_sum = sum(
        SalaryBonus.objects.filter(
            employee=employee, month=month, year=year
        ).values_list('amount', flat=True),
        Decimal('0.00'),
    )
    total_commissions_sum = sum(
        SalesCommission.objects.filter(
            employee=employee, month=month, year=year
        ).values_list('amount', flat=True),
        Decimal('0.00'),
    )
    total_allowances_sum = total_bonuses_sum + total_commissions_sum
    payslip.total_allowances = total_allowances_sum
    payslip.total_deductions = total_deductions_sum
    payslip.net_salary = payslip.basic_salary + total_allowances_sum - total_deductions_sum
    payslip.save(update_fields=['total_allowances', 'total_deductions', 'net_salary'])


@admin_required
@require_POST
def edit_commission_view(request, pk):
    """Admin updates a sales commission's amount and/or note."""
    commission = get_object_or_404(SalesCommission, pk=pk)
    employee = commission.employee

    raw_amount = (request.POST.get('amount') or '').strip()
    note = (request.POST.get('note') or '').strip()
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        amount = Decimal('0')

    if amount <= 0:
        messages.error(request, 'Please enter a valid commission amount.')
        return redirect('accounts:employee_detail', pk=employee.pk)

    commission.amount = amount
    commission.note = note
    commission.save(update_fields=['amount', 'note'])

    # Keep any existing payslip for that period in sync.
    _recalc_payslip_for(employee, commission.month, commission.year)

    messages.success(request, f'Commission updated to PKR {amount:,.2f}.')
    return redirect('accounts:employee_detail', pk=employee.pk)


@admin_required
@require_POST
def delete_commission_view(request, pk):
    """Admin removes a sales commission."""
    commission = get_object_or_404(SalesCommission, pk=pk)
    employee = commission.employee
    month, year = commission.month, commission.year
    amount = commission.amount
    commission.delete()

    # Keep any existing payslip for that period in sync.
    _recalc_payslip_for(employee, month, year)

    messages.success(request, f'Commission of PKR {amount:,.2f} removed.')
    return redirect('accounts:employee_detail', pk=employee.pk)


# ---------------------------------------------------------------------------
# Per-employee salary management (used by the employee detail / report page)
# ---------------------------------------------------------------------------

def _detail_redirect(employee, month=None, year=None):
    """Redirect back to an employee's detail page, preserving the period."""
    url = reverse('accounts:employee_detail', kwargs={'pk': employee.pk})
    if month and year:
        url += f'?m={month}&y={year}'
    return redirect(url)


def _parse_amount(raw):
    try:
        return Decimal((raw or '').strip())
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _period_from_post(request):
    """Read month/year the admin is currently viewing (hidden form fields)."""
    now = timezone.now()
    try:
        month = int(request.POST.get('month') or now.month)
        year = int(request.POST.get('year') or now.year)
    except (ValueError, TypeError):
        month, year = now.month, now.year
    if not (1 <= month <= 12):
        month = now.month
    return month, year


@admin_required
@require_POST
def update_base_salary_view(request, pk):
    """Admin adjusts an employee's base (basic) salary."""
    employee = get_object_or_404(User, pk=pk)
    amount = _parse_amount(request.POST.get('basic_salary'))
    if amount < 0:
        messages.error(request, 'Base salary cannot be negative.')
        return _detail_redirect(employee)

    employee.basic_salary = amount
    employee.save(update_fields=['basic_salary'])

    # Keep current-period payslip (if any) consistent with the new base.
    now = timezone.now()
    month, year = _period_from_post(request)
    payslip = Payslip.objects.filter(employee=employee, month=month, year=year).first()
    if payslip:
        payslip.basic_salary = amount
        payslip.save(update_fields=['basic_salary'])
        _recalc_payslip_for(employee, month, year)

    messages.success(request, f'Base salary updated to PKR {amount:,.2f}.')
    return _detail_redirect(employee, month, year)


@admin_required
@require_POST
def emp_add_deduction_view(request, pk):
    """Add a manual deduction for an employee for the viewed period."""
    employee = get_object_or_404(User, pk=pk)
    month, year = _period_from_post(request)
    amount = _parse_amount(request.POST.get('amount'))
    reason = request.POST.get('reason') or 'other'
    description = (request.POST.get('description') or '').strip()

    if amount <= 0:
        messages.error(request, 'Please enter a valid deduction amount.')
        return _detail_redirect(employee, month, year)

    SalaryDeduction.objects.create(
        employee=employee,
        reason=reason,
        source='manual',
        description=description,
        amount=amount,
        date=timezone.now().date(),
        applied_by=request.user,
        month=month,
        year=year,
    )
    _recalc_payslip_for(employee, month, year)
    messages.success(request, f'Deduction of PKR {amount:,.2f} added.')
    return _detail_redirect(employee, month, year)


@admin_required
@require_POST
def emp_edit_deduction_view(request, pk):
    """Edit a manual deduction."""
    deduction = get_object_or_404(SalaryDeduction, pk=pk)
    employee = deduction.employee

    if deduction.source != 'manual':
        messages.error(request, 'Auto attendance deductions cannot be edited manually.')
        return _detail_redirect(employee, deduction.month, deduction.year)

    amount = _parse_amount(request.POST.get('amount'))
    if amount <= 0:
        messages.error(request, 'Please enter a valid deduction amount.')
        return _detail_redirect(employee, deduction.month, deduction.year)

    deduction.amount = amount
    deduction.reason = request.POST.get('reason') or deduction.reason
    deduction.description = (request.POST.get('description') or '').strip()
    deduction.save(update_fields=['amount', 'reason', 'description'])
    _recalc_payslip_for(employee, deduction.month, deduction.year)
    messages.success(request, f'Deduction updated to PKR {amount:,.2f}.')
    return _detail_redirect(employee, deduction.month, deduction.year)


@admin_required
@require_POST
def emp_delete_deduction_view(request, pk):
    """Remove a manual deduction."""
    deduction = get_object_or_404(SalaryDeduction, pk=pk)
    employee = deduction.employee
    month, year = deduction.month, deduction.year

    if deduction.source != 'manual':
        messages.error(request, 'Auto attendance deductions cannot be removed here.')
        return _detail_redirect(employee, month, year)

    amount = deduction.amount
    deduction.delete()
    _recalc_payslip_for(employee, month, year)
    messages.success(request, f'Deduction of PKR {amount:,.2f} removed.')
    return _detail_redirect(employee, month, year)


@admin_required
@require_POST
def emp_add_bonus_view(request, pk):
    """Add a bonus/allowance for an employee for the viewed period."""
    employee = get_object_or_404(User, pk=pk)
    month, year = _period_from_post(request)
    amount = _parse_amount(request.POST.get('amount'))
    title = (request.POST.get('title') or '').strip() or 'Bonus'

    if amount <= 0:
        messages.error(request, 'Please enter a valid bonus amount.')
        return _detail_redirect(employee, month, year)

    SalaryBonus.objects.create(
        employee=employee,
        title=title,
        amount=amount,
        date=timezone.now().date(),
        applied_by=request.user,
        month=month,
        year=year,
    )
    _recalc_payslip_for(employee, month, year)
    messages.success(request, f'Bonus "{title}" of PKR {amount:,.2f} added.')
    return _detail_redirect(employee, month, year)


@admin_required
@require_POST
def emp_edit_bonus_view(request, pk):
    """Edit a bonus."""
    bonus = get_object_or_404(SalaryBonus, pk=pk)
    employee = bonus.employee
    amount = _parse_amount(request.POST.get('amount'))
    if amount <= 0:
        messages.error(request, 'Please enter a valid bonus amount.')
        return _detail_redirect(employee, bonus.month, bonus.year)

    bonus.amount = amount
    bonus.title = (request.POST.get('title') or '').strip() or bonus.title
    bonus.save(update_fields=['amount', 'title'])
    _recalc_payslip_for(employee, bonus.month, bonus.year)
    messages.success(request, f'Bonus updated to PKR {amount:,.2f}.')
    return _detail_redirect(employee, bonus.month, bonus.year)


@admin_required
@require_POST
def emp_delete_bonus_view(request, pk):
    """Remove a bonus."""
    bonus = get_object_or_404(SalaryBonus, pk=pk)
    employee = bonus.employee
    month, year = bonus.month, bonus.year
    amount = bonus.amount
    bonus.delete()
    _recalc_payslip_for(employee, month, year)
    messages.success(request, f'Bonus of PKR {amount:,.2f} removed.')
    return _detail_redirect(employee, month, year)


@admin_required
def add_bonus_view(request):
    """Add a salary bonus for an employee."""
    form = BonusForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        bonus = form.save(commit=False)
        bonus.applied_by = request.user
        bonus.save()
        messages.success(request, 'Bonus added successfully.')
        return redirect('salary:salary_report')

    context = {'form': form, 'title': 'Add Bonus'}
    return render(request, 'salary/bonus_form.html', context)


@admin_required
def salary_report_view(request):
    """Overview of all employees' salary for a chosen month/year."""
    now = timezone.now()
    month = int(request.GET.get('month', now.month))
    year = int(request.GET.get('year', now.year))

    payslips = Payslip.objects.filter(month=month, year=year).select_related('employee')
    employees_with_no_payslip = User.objects.exclude(
        payslips__month=month,
        payslips__year=year,
    )

    # Employees expected to mark attendance (used for the live-deduction table
    # and the Add Deduction / Add Bonus dropdowns).
    employees = (
        User.objects.filter(is_active=True)
        .exclude(role='admin')
        .exclude(is_superuser=True)
        .order_by('first_name', 'username')
    )

    # Live attendance-based deductions for the selected month — shown WITHOUT
    # having to generate a payslip. Each row carries a full breakdown.
    from .deductions import month_deduction_summary

    live_deductions = []
    live_total = Decimal('0.00')
    for emp in employees:
        summary = month_deduction_summary(emp, year, month)
        if summary['total'] > 0:
            live_deductions.append({'employee': emp, 'summary': summary})
            live_total += summary['total']

    # Sales commissions for the selected period — grouped per employee, shown
    # WITHOUT requiring a payslip (mirrors the live-deductions card).
    commission_qs = (
        SalesCommission.objects.filter(month=month, year=year)
        .select_related('employee')
        .order_by('employee__first_name', '-paid_at')
    )
    commissions_by_emp = {}
    commission_grand_total = Decimal('0.00')
    commission_sales_count = 0
    for c in commission_qs:
        entry = commissions_by_emp.setdefault(
            c.employee_id,
            {'employee': c.employee, 'items': [], 'total': Decimal('0.00'), 'count': 0},
        )
        entry['items'].append(c)
        entry['total'] += c.amount
        entry['count'] += 1
        commission_grand_total += c.amount
        commission_sales_count += 1
    commission_rows = list(commissions_by_emp.values())

    month_choices = list(range(1, 13))
    year_choices = list(range(2020, 2031))

    context = {
        'payslips': payslips,
        'employees_with_no_payslip': employees_with_no_payslip,
        'employees': employees,
        'live_deductions': live_deductions,
        'live_total': live_total,
        'commission_rows': commission_rows,
        'commission_grand_total': commission_grand_total,
        'commission_sales_count': commission_sales_count,
        'selected_month': month,
        'selected_year': year,
        'month_choices': month_choices,
        'year_choices': year_choices,
    }
    return render(request, 'salary/salary_report.html', context)


@login_required
def download_payslip_view(request, pk):
    """Generate and download a payslip as a PDF using ReportLab."""
    payslip = get_object_or_404(Payslip, pk=pk)

    if not request.user.is_admin and payslip.employee != request.user:
        messages.error(request, 'You are not authorised to download this payslip.')
        return redirect('salary:my_salary')

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate,
            Table,
            TableStyle,
            Paragraph,
            Spacer,
        )

        response = HttpResponse(content_type='application/pdf')
        filename = f'payslip_{payslip.employee.username}_{payslip.month}_{payslip.year}.pdf'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        doc = SimpleDocTemplate(response, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Title'],
            fontSize=18,
            spaceAfter=12,
        )
        elements.append(Paragraph('Employee Payslip', title_style))
        elements.append(Spacer(1, 0.5 * cm))

        # Employee info table
        month_name = calendar.month_name[payslip.month]
        emp = payslip.employee
        info_data = [
            ['Employee Name', emp.get_full_name() or emp.username],
            ['Employee ID', emp.employee_id or 'N/A'],
            ['Designation', emp.designation or 'N/A'],
            ['Department', str(emp.department) if emp.department else 'N/A'],
            ['Pay Period', f'{month_name} {payslip.year}'],
            ['Status', payslip.get_status_display()],
        ]
        info_table = Table(info_data, colWidths=[5 * cm, 10 * cm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.5 * cm))

        # Attendance summary
        elements.append(Paragraph('Attendance Summary', styles['Heading2']))
        att_data = [
            ['Working Days', 'Present Days', 'Absent Days'],
            [str(payslip.working_days), str(payslip.present_days), str(payslip.absent_days)],
        ]
        att_table = Table(att_data, colWidths=[5 * cm, 5 * cm, 5 * cm])
        att_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343a40')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(att_table)
        elements.append(Spacer(1, 0.5 * cm))

        # Earnings & Deductions
        elements.append(Paragraph('Salary Breakdown', styles['Heading2']))

        deductions = SalaryDeduction.objects.filter(
            employee=payslip.employee,
            month=payslip.month,
            year=payslip.year,
        )
        bonuses = SalaryBonus.objects.filter(
            employee=payslip.employee,
            month=payslip.month,
            year=payslip.year,
        )
        commissions = SalesCommission.objects.filter(
            employee=payslip.employee,
            month=payslip.month,
            year=payslip.year,
        )

        earnings_rows = [['Earnings', 'Amount (PKR)']]
        earnings_rows.append(['Basic Salary', f'{payslip.basic_salary:,.2f}'])
        for bonus in bonuses:
            earnings_rows.append([bonus.title, f'{bonus.amount:,.2f}'])
        for comm in commissions:
            label = 'Sales Commission'
            if comm.note:
                label = f'Sales Commission ({comm.note})'
            earnings_rows.append([label, f'{comm.amount:,.2f}'])
        earnings_rows.append(['Total Earnings', f'{payslip.basic_salary + payslip.total_allowances:,.2f}'])

        deduction_rows = [['Deductions', 'Amount (PKR)']]
        for ded in deductions:
            deduction_rows.append([ded.get_reason_display(), f'{ded.amount:,.2f}'])
        deduction_rows.append(['Total Deductions', f'{payslip.total_deductions:,.2f}'])

        def make_table(data):
            t = Table(data, colWidths=[10 * cm, 5 * cm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            return t

        elements.append(make_table(earnings_rows))
        elements.append(Spacer(1, 0.3 * cm))
        elements.append(make_table(deduction_rows))
        elements.append(Spacer(1, 0.5 * cm))

        # Net salary
        net_data = [
            ['NET SALARY', f'PKR {payslip.net_salary:,.2f}'],
        ]
        net_table = Table(net_data, colWidths=[10 * cm, 5 * cm])
        net_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#198754')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(net_table)

        if payslip.notes:
            elements.append(Spacer(1, 0.5 * cm))
            elements.append(Paragraph('Notes', styles['Heading3']))
            elements.append(Paragraph(payslip.notes, styles['Normal']))

        doc.build(elements)
        return response

    except ImportError:
        # Fallback: plain HTML response when ReportLab is not installed
        month_name = calendar.month_name[payslip.month]
        emp = payslip.employee
        html = f"""
        <html><head><title>Payslip</title></head><body>
        <h1>Employee Payslip</h1>
        <p><strong>Name:</strong> {emp.get_full_name() or emp.username}</p>
        <p><strong>Period:</strong> {month_name} {payslip.year}</p>
        <p><strong>Basic Salary:</strong> {payslip.basic_salary}</p>
        <p><strong>Total Allowances/Bonuses:</strong> {payslip.total_allowances}</p>
        <p><strong>Total Deductions:</strong> {payslip.total_deductions}</p>
        <p><strong>Net Salary:</strong> {payslip.net_salary}</p>
        <p><strong>Status:</strong> {payslip.get_status_display()}</p>
        </body></html>
        """
        return HttpResponse(html, content_type='text/html')


@admin_required
def process_payroll_view(request):
    """Mark all draft payslips for a given month/year as 'processed'."""
    if request.method == 'POST':
        month = int(request.POST.get('month', timezone.now().month))
        year = int(request.POST.get('year', timezone.now().year))

        updated = Payslip.objects.filter(
            month=month,
            year=year,
            status='draft',
        ).update(status='processed')

        messages.success(request, f'{updated} payslip(s) marked as processed for {month}/{year}.')
        return redirect('salary:salary_report')

    now = timezone.now()
    month_choices = list(range(1, 13))
    year_choices = list(range(2020, 2031))
    context = {
        'month_choices': month_choices,
        'year_choices': year_choices,
        'current_month': now.month,
        'current_year': now.year,
    }
    return render(request, 'salary/process_payroll.html', context)
