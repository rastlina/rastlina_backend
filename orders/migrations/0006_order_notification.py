import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('orders', '0005_order_awb_code_order_shiprocket_order_id_and_more')]
    operations = [migrations.CreateModel(
        name='OrderNotification',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('recipient', models.EmailField(default='info.rastlina@gmail.com', max_length=254)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('sent_at', models.DateTimeField(blank=True, null=True)),
            ('attempts', models.PositiveIntegerField(default=0)),
            ('next_attempt_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('last_error', models.CharField(blank=True, max_length=100)),
            ('order', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='merchant_notification', to='orders.order')),
        ], options={'ordering': ['created_at']})]

