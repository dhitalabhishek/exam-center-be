from django.apps import AppConfig


class AppexamConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "appExam"

    def ready(self):
        import appExam.signals  # noqa: F401
