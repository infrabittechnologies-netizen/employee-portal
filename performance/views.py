from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import admin_required, manager_required
from .forms import KPIForm, KPIUpdateForm, PerformanceReviewForm
from .models import KPI, PerformanceReview

User = get_user_model()


@login_required
def my_performance_view(request):
    """Show the logged-in employee's performance review history and KPIs."""
    reviews = PerformanceReview.objects.filter(
        employee=request.user
    ).select_related('reviewed_by').order_by('-created_at')

    kpis = KPI.objects.filter(employee=request.user).order_by('-created_at')

    context = {
        'reviews': reviews,
        'kpis': kpis,
    }
    return render(request, 'performance/my_performance.html', context)


@manager_required
def performance_review_create_view(request):
    """Create a performance review for an employee (manager/admin only)."""
    form = PerformanceReviewForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        review = form.save(commit=False)
        review.reviewed_by = request.user
        review.save()
        messages.success(
            request,
            f'Performance review created for '
            f'{review.employee.get_full_name() or review.employee.username}.',
        )
        return redirect('performance:review_detail', pk=review.pk)

    context = {'form': form, 'title': 'Create Performance Review'}
    return render(request, 'performance/review_form.html', context)


@login_required
def performance_review_detail_view(request, pk):
    """View a single performance review. Employees can only view their own."""
    review = get_object_or_404(PerformanceReview, pk=pk)

    if not request.user.is_manager_role and review.employee != request.user:
        messages.error(request, 'You are not authorised to view this review.')
        return redirect('performance:my_performance')

    context = {'review': review}
    return render(request, 'performance/review_detail.html', context)


@login_required
def kpi_list_view(request):
    """List KPIs for the logged-in employee (managers see all)."""
    if request.user.is_manager_role:
        employee_id = request.GET.get('employee')
        if employee_id:
            kpis = KPI.objects.filter(employee_id=employee_id).select_related('employee')
        else:
            kpis = KPI.objects.all().select_related('employee')
        employees = User.objects.all().order_by('first_name', 'last_name')
    else:
        kpis = KPI.objects.filter(employee=request.user)
        employees = None

    context = {
        'kpis': kpis,
        'employees': employees,
        'selected_employee': request.GET.get('employee'),
    }
    return render(request, 'performance/kpi_list.html', context)


@manager_required
def kpi_create_view(request):
    """Create a KPI for an employee (manager/admin only)."""
    form = KPIForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        kpi = form.save()
        messages.success(
            request,
            f'KPI created for {kpi.employee.get_full_name() or kpi.employee.username}.',
        )
        return redirect('performance:kpi_list')

    context = {'form': form, 'title': 'Create KPI'}
    return render(request, 'performance/kpi_form.html', context)


@login_required
def kpi_update_view(request, pk):
    """
    Update a KPI.
    - Employees can only update achieved and status on their own KPIs.
    - Managers/admins can update any field on any KPI.
    """
    kpi = get_object_or_404(KPI, pk=pk)

    if not request.user.is_manager_role and kpi.employee != request.user:
        messages.error(request, 'You are not authorised to update this KPI.')
        return redirect('performance:kpi_list')

    if request.user.is_manager_role:
        FormClass = KPIForm
    else:
        FormClass = KPIUpdateForm

    form = FormClass(request.POST or None, instance=kpi)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'KPI updated successfully.')
        return redirect('performance:kpi_list')

    context = {'form': form, 'kpi': kpi, 'title': 'Update KPI'}
    return render(request, 'performance/kpi_form.html', context)


@admin_required
def all_performance_view(request):
    """Admin overview of all employees' latest ratings and KPI statuses."""
    employees = User.objects.all().order_by('first_name', 'last_name')

    employee_data = []
    for emp in employees:
        latest_review = PerformanceReview.objects.filter(
            employee=emp
        ).order_by('-created_at').first()

        kpi_counts = {
            'total': KPI.objects.filter(employee=emp).count(),
            'achieved': KPI.objects.filter(employee=emp, status='achieved').count(),
            'missed': KPI.objects.filter(employee=emp, status='missed').count(),
            'in_progress': KPI.objects.filter(employee=emp, status='in_progress').count(),
            'on_track': KPI.objects.filter(employee=emp, status='on_track').count(),
        }

        employee_data.append({
            'employee': emp,
            'latest_review': latest_review,
            'kpi_counts': kpi_counts,
        })

    context = {'employee_data': employee_data}
    return render(request, 'performance/all_performance.html', context)
