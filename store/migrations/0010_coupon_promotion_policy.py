from django.db import migrations, models


def configure_existing_codes(apps, schema_editor):
    Coupon = apps.get_model('store', 'Coupon')
    Coupon.objects.filter(code__iexact='10% OFF').update(auto_apply=True)
    Coupon.objects.filter(code__iexact='DIWALI10').update(auto_apply=False, combine_with_automatic=True, staff_only=False)
    # Keep the owner-configured discount amount, dates and usage limit.
    Coupon.objects.filter(code__iexact='INFLU').update(auto_apply=False, combine_with_automatic=False,
        staff_only=True, free_shipping=True, min_order_value=0)


class Migration(migrations.Migration):
    dependencies = [('store', '0009_watchandshop_mp4_upload')]
    operations = [
        migrations.AddField('coupon', 'auto_apply', models.BooleanField(default=False, help_text='Apply automatically when the minimum spend is met.')),
        migrations.AddField('coupon', 'combine_with_automatic', models.BooleanField(default=False, help_text='Allow this entered code plus the best automatic offer. Percentages use the original subtotal.')),
        migrations.AddField('coupon', 'free_shipping', models.BooleanField(default=False, help_text='Waive delivery charges for this coupon. Set minimum order value to 0 for no minimum.')),
        migrations.AddField('coupon', 'staff_only', models.BooleanField(default=False, help_text='Private creator coupon. Only signed-in staff can use it; never listed publicly.')),
        migrations.RunPython(configure_existing_codes, migrations.RunPython.noop),
    ]
