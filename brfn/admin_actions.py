from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME


class AdminActionSelectLabelMixin:
    """
    Small admin UX mixin used by app admin classes.

    It ensures the action dropdown keeps Django's default behavior while
    exposing a stable extension point for projects that want custom labels.
    """

    action_select_label = "Action:"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.setdefault("action_checkbox_name", ACTION_CHECKBOX_NAME)
        extra_context.setdefault("action_select_label", self.action_select_label)
        return super().changelist_view(request, extra_context=extra_context)
