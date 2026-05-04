from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from django.contrib.auth import get_user_model
from rest_framework import generics, viewsets, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import SavedAddress
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserSerializer,
    SavedAddressSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """POST /api/auth/signup/ — Email + Password signup"""
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    """POST /api/auth/login/ — Returns JWT + user data"""
    serializer_class = CustomTokenObtainPairSerializer


class UserProfileView(APIView):
    """GET/PATCH /api/auth/user/ — View and update profile"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SavedAddressViewSet(viewsets.ModelViewSet):
    """CRUD for saved addresses — max 3 per user"""
    permission_classes = [IsAuthenticated]
    serializer_class = SavedAddressSerializer

    def get_queryset(self):
        return SavedAddress.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        addr = self.get_object()
        addr.is_default = True
        addr.save()  # save() handles clearing other defaults
        return Response(SavedAddressSerializer(addr).data)


class GoogleLogin(SocialLoginView):
    """
    POST /api/auth/google/
    Body: { "code": "<google_auth_code>", "callback_url": "postmessage" }
    
    Flow:
    1. Frontend triggers Google OAuth popup → gets auth code
    2. Sends code to this endpoint
    3. Django exchanges code for token with Google
    4. Creates/finds user → returns JWT
    """
    adapter_class = GoogleOAuth2Adapter
    client_class = OAuth2Client
    callback_url = "postmessage"

    def post(self, request, *args, **kwargs):
        # Ensure callback_url is set correctly
        if hasattr(request.data, '_mutable'):
            request.data._mutable = True
        request.data['callback_url'] = "postmessage"
        return super().post(request, *args, **kwargs)