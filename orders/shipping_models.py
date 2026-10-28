from django.db import models
from django.utils import timezone


class ShiprocketSync(models.Model):
    order = models.OneToOneField('orders.Order', on_delete=models.CASCADE, related_name='shipping_sync')
    status = models.CharField(max_length=20, default='Pending', choices=[
        ('Pending', 'Pending'), ('Synced', 'Synced'), ('Error', 'Needs attention'), ('Skipped', 'Skipped')])
    plant_count = models.PositiveIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.CharField(max_length=255, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

