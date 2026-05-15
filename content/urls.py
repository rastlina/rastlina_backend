from django.urls import path
from .views import HomeContentAPIView

urlpatterns = [
    path('home-content/', HomeContentAPIView.as_view()),
]