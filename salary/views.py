import calendar
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import admin_required
from attendance.models import Attendance
from .forms import BonusForm, DeductionForm, GeneratePayslipForm
from .models import Payslip, SalaryBonus, SalaryDeduction

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

    context = {
        'payslips': payslips,
        'current_deductions': current_deductions,
        'current_bonuses': current_bonuses,
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

    context = {
        'payslip': payslip,
        'deductions': deductions,
        'bonuses': bonuses,
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

        net_salary = basic_salary + total_bonuses_sum - total_deductions_sum

        payslip, created = Payslip.objects.update_or_create(
            employee=employee,
            month=month,
            year=year,
            defaults={
                'basic_salary': basic_salary,
                'total_allowances': total_bonuses_sum,
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

        # Link orphan deductions/bonuses to this payslip
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

    month_choices = list(range(1, 13))
    year_choices = list(range(2020, 2031))

    context = {
        'payslips': payslips,
        'employees_with_no_payslip': employees_with_no_payslip,
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

        earnings_rows = [['Earnings', 'Amount (PKR)']]
        earnings_rows.append(['Basic Salary', f'{payslip.basic_salary:,.2f}'])
        for bonus in bonuses:
            earnings_rows.append([bonus.title, f'{bonus.amount:,.2f}'])
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
