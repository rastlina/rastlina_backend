from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('store', '0010_coupon_promotion_policy'),
        ('store', '0010_merge_watchandshop_mp4'),
    ]
    operations = [migrations.AlterField(
        model_name='watchandshop', name='video_url',
        field=models.URLField(max_length=500, blank=True, default='', help_text='Legacy video URL (unused).'),
    )]
