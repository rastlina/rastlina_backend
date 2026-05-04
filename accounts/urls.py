from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegisterView,
    CustomTokenObtainPairView,
    UserProfileView,
    GoogleLogin,
    SavedAddressViewSet,
)

router = DefaultRouter()
router.register(r'addresses', SavedAddressViewSet, basename='savedaddress')

urlpatterns = [
    path('signup/', RegisterView.as_view(), name='register'),
    path('login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('user/', UserProfileView.as_view(), name='user_profile'),
    path('google/', GoogleLogin.as_view(), name='google_login'),
    path('', include(router.urls)),
]