import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.utils import timezone
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token
from rest_framework import permissions
from rest_framework.exceptions import APIException, Throttled, ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import EmailOTP, User


def user_json(u):
    return {'id': u.id, 'email': u.email, 'first_name': u.first_name, 'last_name': u.last_name, 'is_staff': u.is_staff}


class Unavailable(APIException):
    status_code = 503
    default_detail = 'Google sign-in is not available.'


def bad(msg):
    return DRFValidationError({'detail': msg})


def promote_admin(user):
    if user.email in settings.ADMIN_EMAILS and not user.is_staff:
        user.is_staff = True
        user.save(update_fields=['is_staff'])


def session_for(user):
    promote_admin(user)
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh), 'user': user_json(user)}


def clean_email(value):
    value = (value or '').strip().lower()
    try:
        validate_email(value)
    except ValidationError:
        raise DRFValidationError({'detail': 'Enter a valid email address.'})
    return value


class OTPRequest(APIView):
    throttle_scope = 'otp_request'

    def post(self, request):
        email = clean_email(request.data.get('email'))
        now = timezone.now()
        recent = EmailOTP.objects.filter(
            email=email, created_at__gte=now - timedelta(seconds=settings.OTP_RESEND_SECONDS)).exists()
        if recent:
            raise Throttled(wait=settings.OTP_RESEND_SECONDS, detail='Please wait a minute before requesting another code.')
        code = f'{secrets.randbelow(10**6):06d}'
        EmailOTP.objects.filter(email=email, used=False).update(used=True)  # invalidate older codes
        EmailOTP.objects.create(email=email, code_hash=EmailOTP.digest(email, code),
                                expires_at=now + timedelta(minutes=settings.OTP_TTL_MINUTES))
        send_mail(
            'Your Techive sign-in code',
            f'Your Techive IT Solutions sign-in code is {code}.\n\n'
            f'It expires in {settings.OTP_TTL_MINUTES} minutes. If you did not request it, ignore this email.',
            settings.DEFAULT_FROM_EMAIL, [email])
        # Same response whether or not the email is known: no user enumeration.
        return Response({'detail': 'If the email is valid, a code has been sent.'})


class OTPVerify(APIView):
    throttle_scope = 'otp_verify'

    def post(self, request):
        email = clean_email(request.data.get('email'))
        code = str(request.data.get('code') or '').strip()
        otp = EmailOTP.objects.filter(email=email, used=False, expires_at__gt=timezone.now()).order_by('-created_at').first()
        if not otp or otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise bad('Invalid or expired code.')
        if not secrets.compare_digest(otp.code_hash, EmailOTP.digest(email, code)):
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            raise bad('Invalid or expired code.')
        otp.used = True
        otp.save(update_fields=['used'])
        user, _ = User.objects.get_or_create(email=email, defaults={'is_active': True})
        if user.password == '':  # safety: never leave a usable empty password
            user.set_unusable_password(); user.save(update_fields=['password'])
        if not user.is_active:
            raise bad('This account is disabled.')
        return Response(session_for(user))


class GoogleAuth(APIView):
    throttle_scope = 'google'

    def post(self, request):
        credential = request.data.get('credential')
        if not settings.GOOGLE_CLIENT_ID:
            raise Unavailable()
        if not credential:
            raise bad('Google sign-in failed.')
        try:
            info = id_token.verify_oauth2_token(credential, g_requests.Request(), settings.GOOGLE_CLIENT_ID)
        except ValueError:
            raise bad('Google sign-in failed.')
        if not info.get('email_verified') or not info.get('email'):
            raise bad('Your Google email is not verified.')
        email = info['email'].lower()
        user, created = User.objects.get_or_create(email=email, defaults={
            'first_name': info.get('given_name', ''), 'last_name': info.get('family_name', '')})
        if not user.is_active:
            raise bad('This account is disabled.')
        if not created and not user.first_name and info.get('given_name'):
            user.first_name, user.last_name = info['given_name'], info.get('family_name', '')
            user.save(update_fields=['first_name', 'last_name'])
        return Response(session_for(user))


class Me(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(user_json(request.user))

    def patch(self, request):
        for f in ('first_name', 'last_name'):
            if f in request.data:
                setattr(request.user, f, str(request.data[f])[:150].strip())
        request.user.save()
        return Response(user_json(request.user))
