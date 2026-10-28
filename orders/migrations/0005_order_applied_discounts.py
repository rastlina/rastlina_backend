from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('orders', '0004_alter_returnrequest_options')]
    operations = [migrations.AddField('order', 'applied_discounts', models.JSONField(default=list, blank=True))]
