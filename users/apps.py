from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"

    def ready(self) -> None:
        import brfn.admin_tweaks  # noqa: F401 — project-wide admin labels (idempotent)
