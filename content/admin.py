from django.contrib import admin
from .models import AnnouncementBar, SocialProofItem


@admin.register(AnnouncementBar)
class AnnouncementBarAdmin(admin.ModelAdmin):
    list_display = ['text', 'is_active', 'order']
    list_editable = ['is_active', 'order']


@admin.register(SocialProofItem)
class SocialProofItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'subtitle', 'icon', 'is_active', 'order']
    list_editable = ['is_active', 'order']