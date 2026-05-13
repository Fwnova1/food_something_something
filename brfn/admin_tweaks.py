"""
Project-wide Django admin tweaks (entry point from ``users.apps.UsersConfig.ready``).

Implementation lives in ``brfn.admin_actions`` to keep a single module for admin UI helpers.
"""

from brfn.admin_actions import install_admin_action_placeholder_globally

install_admin_action_placeholder_globally()
