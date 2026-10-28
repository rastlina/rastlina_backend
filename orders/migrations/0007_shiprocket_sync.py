import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('orders', '0006_order_notification')]
    operations = [migrations.CreateModel(name='ShiprocketSync', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('status', models.CharField(max_length=20, default='Pending', choices=[('Pending','Pending'), ('Synced','Synced'), ('Error','Needs attention'), ('Skipped','Skipped')])),
        ('plant_count', models.PositiveIntegerField(default=0)),
        ('attempts', models.PositiveIntegerField(default=0)),
        ('next_attempt_at', models.DateTimeField(default=django.utils.timezone.now)),
        ('last_error', models.CharField(max_length=255, blank=True)),
        ('synced_at', models.DateTimeField(null=True, blank=True)),
        ('created_at', models.DateTimeField(auto_now_add=True)),
        ('order', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='orders.order', related_name='shipping_sync')),
    ])]
