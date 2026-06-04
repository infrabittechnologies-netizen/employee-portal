from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def admin_required(view_func):
    """
    Decorator that restricts access to users whose role is 'admin'
    (or who are Django superusers).  Everyone else is bounced to the
    dashboard with an error message.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_admin:
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('dashboard:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def manager_required(view_func):
    """
    Decorator that restricts access to users whose role is 'manager'
    or 'admin' (or who are Django superusers).  Regular employees are
    bounced to the dashboard with an error message.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_manager_role:
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('dashboard:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper
