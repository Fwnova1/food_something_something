from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from brfn.admin_actions import AdminActionSelectLabelMixin

from .models import User


class CustomUserAdmin(AdminActionSelectLabelMixin, UserAdmin):
    """User admin with readable bulk-action placeholder."""

    pass


admin.site.register(User, CustomUserAdmin)