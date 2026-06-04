from django.contrib import admin
from .models import Announcement, Holiday


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'is_optional', 'created_by')
    list_filter = ('is_optional', 'date')
    search_fields = ('name', 'description')
    ordering = ('date',)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'posted_by', 'posted_on', 'target', 'department', 'is_active')
    list_filter = ('target', 'is_active', 'posted_on')
    search_fields = ('title', 'content', 'posted_by__username')
    ordering = ('-posted_on',)
    readonly_fields = ('posted_on',)
    list_editable = ('is_active',)
