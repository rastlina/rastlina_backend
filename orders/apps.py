from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'orders'

    def ready(self):
        from . import notification_signals  # noqa: F401
        from . import shipping_signals  # noqa: F401

