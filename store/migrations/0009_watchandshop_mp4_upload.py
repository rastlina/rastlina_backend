from django.db import migrations, models
import django.core.validators
import store.validators


class Migration(migrations.Migration):
    dependencies = [("store", "0008_watchandshop_slug_alter_productimage_is_primary")]

    operations = [
        migrations.AddField(
            model_name="watchandshop", name="video_file",
            field=models.FileField(
                blank=True, upload_to="watch_shop/videos/",
                validators=[django.core.validators.FileExtensionValidator(["mp4"]),
                            store.validators.validate_mp4_upload],
                help_text="Upload an H.264 MP4, ideally under 5 MB (maximum 20 MB).",
            ),
        ),
        migrations.AlterField(
            model_name="watchandshop", name="video_url",
            field=models.URLField(blank=True, default="", help_text="Legacy video URL (unused)."),
        ),
        migrations.AlterField(
            model_name="watchandshop", name="thumbnail",
            field=models.ImageField(
                blank=True, upload_to="watch_shop/",
                help_text="Optional preview image. Uses the product image when left blank.",
            ),
        ),
    ]

