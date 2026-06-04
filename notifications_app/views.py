from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def notification_list_view(request):
    """List all notifications for the current user and mark unread ones as read."""
    notifications = Notification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')

    # Mark all unread notifications as read when the page is viewed
    Notification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).update(is_read=True)

    context = {'notifications': notifications}
    return render(request, 'notifications_app/notification_list.html', context)


@require_POST
@login_required
def mark_read_view(request, pk):
    """Mark a single notification as read. Returns JSON."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    return JsonResponse({'status': 'ok', 'id': pk, 'is_read': True})


@require_POST
@login_required
def mark_all_read_view(request):
    """Mark all of the current user's notifications as read."""
    updated = Notification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).update(is_read=True)
    return JsonResponse({'status': 'ok', 'updated': updated})


@login_required
def notification_count_view(request):
    """Return the number of unread notifications for the current user as JSON."""
    count = Notification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).count()
    return JsonResponse({'unread_count': count})
