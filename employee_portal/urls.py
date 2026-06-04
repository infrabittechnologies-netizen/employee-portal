from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    path('', lambda request: redirect('dashboard:dashboard'), name='home'),
    path('admin-site/', admin.site.urls),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('attendance/', include('attendance.urls', namespace='attendance')),
    path('leaves/', include('leaves.urls', namespace='leaves')),
    path('salary/', include('salary.urls', namespace='salary')),
    path('performance/', include('performance.urls', namespace='performance')),
    path('holidays/', include('holidays.urls', namespace='holidays')),
    path('notifications/', include('notifications_app.urls', namespace='notifications_app')),
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
