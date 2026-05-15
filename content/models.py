from django.db import models


class AnnouncementBar(models.Model):
    text = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.text


class SocialProofItem(models.Model):
    ICON_CHOICES = [
        ('smile', 'Smile'),
        ('truck', 'Truck'),
        ('star', 'Star'),
    ]

    icon = models.CharField(max_length=20, choices=ICON_CHOICES)
    title = models.CharField(max_length=100)
    subtitle = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.title