from rest_framework.views import APIView
from rest_framework.response import Response

from .models import AnnouncementBar, SocialProofItem
from .serializers import (
    AnnouncementBarSerializer,
    SocialProofItemSerializer,
)


class HomeContentAPIView(APIView):
    permission_classes = []

    def get(self, request):
        announcements = AnnouncementBar.objects.filter(
            is_active=True
        )

        social_proofs = SocialProofItem.objects.filter(
            is_active=True
        )

        return Response({
            "announcement_bars": AnnouncementBarSerializer(
                announcements,
                many=True
            ).data,

            "social_proof_items": SocialProofItemSerializer(
                social_proofs,
                many=True
            ).data,
        })