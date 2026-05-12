"""
Shared Django admin helpers: bulk-action dropdown placeholder label.

Django's default empty option uses ``models.BLANK_CHOICE_DASH`` (``---------``). We replace that
with ``Select Action`` for readability.

* **``AdminActionSelectLabelMixin``** — inherit on custom ``ModelAdmin`` subclasses.
* **``install_admin_action_placeholder_globally()``** — monkey-patch ``ModelAdmin`` so
  ``admin.site.register(Model)`` defaults and third-party admins get the same label.

Both paths call the same relabel logic (no duplicated string handling).
"""

from __future__ import annotations

from django.contrib.admin import ModelAdmin
from django.db import models

ADMIN_ACTION_SELECT_PLACEHOLDER = "Select Action"

# Captured before any monkey-patch so mixins and the global wrapper stay consistent.
_orig_model_admin_get_action_choices = ModelAdmin.get_action_choices

_global_placeholder_installed = False


def relabel_admin_action_placeholder(choices: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Replace the blank action option label with ``ADMIN_ACTION_SELECT_PLACEHOLDER``."""
    out = list(choices)
    for i, (value, _label) in enumerate(out):
        if value == "":
            out[i] = ("", ADMIN_ACTION_SELECT_PLACEHOLDER)
            break
    return out


class AdminActionSelectLabelMixin:
    """Use on ``ModelAdmin`` subclasses so the action dropdown shows ``Select Action``."""

    def get_action_choices(self, request, default_choices=models.BLANK_CHOICE_DASH):
        raw = _orig_model_admin_get_action_choices(self, request, default_choices)
        return relabel_admin_action_placeholder(raw)


def install_admin_action_placeholder_globally() -> None:
    """
    Patch ``ModelAdmin.get_action_choices`` once (covers ``admin.site.register(Model)`` defaults).

    Idempotent.
    """
    global _global_placeholder_installed
    if _global_placeholder_installed:
        return

    def get_action_choices(self, request, default_choices=models.BLANK_CHOICE_DASH):
        raw = _orig_model_admin_get_action_choices(self, request, default_choices)
        return relabel_admin_action_placeholder(raw)

    ModelAdmin.get_action_choices = get_action_choices  # type: ignore[method-assign]
    _global_placeholder_installed = True
