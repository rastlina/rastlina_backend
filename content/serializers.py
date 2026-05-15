from rest_framework import serializers
from .models import AnnouncementBar, SocialProofItem


class AnnouncementBarSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnnouncementBar
        fields = '__all__'


class SocialProofItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialProofItem
        fields = '__all__'