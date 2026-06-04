from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import admin_required
from .forms import AnnouncementForm, HolidayForm
from .models import Announcement, Holiday


@login_required
def holiday_list_view(request):
    """Show all holidays for the current year."""
    current_year = timezone.now().year
    year = int(request.GET.get('year', current_year))
    holidays = Holiday.objects.filter(date__year=year).order_by('date')

    year_choices = list(range(current_year - 1, current_year + 3))

    context = {
        'holidays': holidays,
        'selected_year': year,
        'year_choices': year_choices,
        'current_year': current_year,
    }
    return render(request, 'holidays/holiday_list.html', context)


@admin_required
def admin_holiday_view(request):
    """Add a new holiday (GET shows form + list, POST adds holiday)."""
    current_year = timezone.now().year
    holidays = Holiday.objects.filter(date__year=current_year).order_by('date')
    form = HolidayForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        holiday = form.save(commit=False)
        holiday.created_by = request.user
        holiday.save()
        messages.success(request, f'Holiday "{holiday.name}" added successfully.')
        return redirect('holidays:admin_holiday')

    context = {
        'form': form,
        'holidays': holidays,
        'current_year': current_year,
    }
    return render(request, 'holidays/admin_holiday.html', context)


@login_required
def announcement_list_view(request):
    """Show announcements relevant to the current user."""
    user = request.user
    announcements = Announcement.objects.filter(is_active=True)

    if not user.is_admin:
        # Filter by relevance: all, manager (if manager), or department-specific
        from django.db.models import Q
        query = Q(target='all')
        if user.is_manager_role:
            query |= Q(target='manager')
        if user.department:
            query |= Q(target='department', department=user.department)
        announcements = announcements.filter(query)

    announcements = announcements.select_related('posted_by', 'department').order_by('-posted_on')

    context = {'announcements': announcements}
    return render(request, 'holidays/announcement_list.html', context)


@admin_required
def admin_announcement_view(request):
    """Create a new announcement (admin only)."""
    form = AnnouncementForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        announcement = form.save(commit=False)
        announcement.posted_by = request.user
        announcement.save()
        messages.success(request, f'Announcement "{announcement.title}" created successfully.')
        return redirect('holidays:announcement_list')

    context = {'form': form, 'title': 'Create Announcement'}
    return render(request, 'holidays/announcement_form.html', context)


@admin_required
def delete_announcement_view(request, pk):
    """Soft-delete (deactivate) an announcement (admin only)."""
    announcement = get_object_or_404(Announcement, pk=pk)

    if request.method == 'POST':
        announcement.is_active = False
        announcement.save(update_fields=['is_active'])
        messages.success(request, f'Announcement "{announcement.title}" deleted.')
        return redirect('holidays:announcement_list')

    context = {'announcement': announcement}
    return render(request, 'holidays/confirm_delete.html', context)
