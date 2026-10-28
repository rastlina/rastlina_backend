from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0009_alter_watchandshop_video_url"),
        ("store", "0009_watchandshop_mp4_upload"),
    ]
    operations = [
        migrations.AlterField(
            model_name="watchandshop", name="video_url",
            field=models.URLField(max_length=500, blank=True, default="",
                                  help_text="Legacy video URL (unused)."),
        ),
    ]
