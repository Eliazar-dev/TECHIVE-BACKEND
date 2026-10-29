from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('otp/request/', views.OTPRequest.as_view()),
    path('otp/verify/', views.OTPVerify.as_view()),
    path('google/', views.GoogleAuth.as_view()),
    path('token/refresh/', TokenRefreshView.as_view()),
    path('me/', views.Me.as_view()),
]
