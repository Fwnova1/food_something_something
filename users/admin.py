from django.contrib import admin
from .models import SecurityEvent, User

admin.site.register(User)


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "user", "path", "ip_address", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__username", "detail", "path", "ip_address")
    readonly_fields = ("event_type", "user", "path", "detail", "ip_address", "created_at")
