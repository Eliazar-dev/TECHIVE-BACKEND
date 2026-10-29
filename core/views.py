import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from .models import Quote, WaitlistEntry

log = logging.getLogger(__name__)


# ---------- serializers ----------
class QuoteIn(serializers.ModelSerializer):
    class Meta:
        model = Quote
        fields = ['name', 'phone', 'service', 'budget', 'message']
        extra_kwargs = {'name': {'required': False, 'allow_blank': True}}  # blank -> falls back to profile name


class QuoteAdminSer(serializers.ModelSerializer):
    class Meta:
        model = Quote
        fields = ['id', 'name', 'email', 'phone', 'service', 'budget', 'message', 'status', 'notes', 'created_at']
        read_only_fields = ['id', 'name', 'email', 'phone', 'service', 'budget', 'message', 'created_at']


class UserAdminSer(serializers.ModelSerializer):
    quotes = serializers.IntegerField(source='quote_count', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'is_staff', 'date_joined', 'last_login', 'quotes']


class WaitlistSer(serializers.ModelSerializer):
    class Meta:
        model = WaitlistEntry
        fields = ['id', 'email', 'name', 'course', 'created_at']


# ---------- public / signed-in ----------
class QuoteCreate(generics.CreateAPIView):
    """Quotes require a signed-in (OTP or Google) user."""
    permission_classes = [IsAuthenticated]
    serializer_class = QuoteIn
    throttle_scope = 'quote'

    def perform_create(self, serializer):
        u = self.request.user
        name = serializer.validated_data.get('name') or f'{u.first_name} {u.last_name}'.strip() or u.email.split('@')[0]
        q = serializer.save(user=u, email=u.email, name=name)
        try:
            send_mail(
                f'New quote request: {q.service or "General"} - {q.name}',
                f'Name: {q.name}\nEmail: {q.email}\nPhone: {q.phone}\nService: {q.service}\nBudget: {q.budget}\n\n{q.message}',
                settings.DEFAULT_FROM_EMAIL, [settings.TEAM_EMAIL], fail_silently=False)
            send_mail(
                'We received your quote request',
                f'Hi {q.name},\n\nThanks for contacting Techive IT Solutions. We received your request and will reply within one business day.\n\nTechive IT Solutions',
                settings.DEFAULT_FROM_EMAIL, [q.email], fail_silently=False)
        except Exception:
            log.exception('Quote email failed (quote %s saved)', q.pk)

    def create(self, request, *args, **kwargs):
        super().create(request, *args, **kwargs)
        return Response({'detail': 'ok'}, status=201)


class WaitlistCreate(APIView):
    permission_classes = []
    throttle_scope = 'waitlist'

    def post(self, request):
        s = WaitlistSer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        WaitlistEntry.objects.get_or_create(
            email=d['email'].lower(), defaults={'name': d.get('name', ''), 'course': d.get('course', '')})
        return Response({'detail': 'ok'}, status=201)  # same answer whether new or existing


# ---------- staff-only (React /admin) ----------
class AdminStats(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        week = timezone.now() - timedelta(days=7)
        return Response({
            'quotes_total': Quote.objects.count(),
            'quotes_new': Quote.objects.filter(status='new').count(),
            'quotes_week': Quote.objects.filter(created_at__gte=week).count(),
            'users_total': User.objects.count(),
            'waitlist_total': WaitlistEntry.objects.count(),
            'by_service': list(Quote.objects.exclude(service='').values('service').annotate(n=Count('id')).order_by('-n')[:8]),
            'by_status': {r['status']: r['n'] for r in Quote.objects.values('status').annotate(n=Count('id'))},
        })


class AdminQuoteList(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = QuoteAdminSer

    def get_queryset(self):
        qs = Quote.objects.all()
        st = self.request.query_params.get('status')
        return qs.filter(status=st) if st else qs


class AdminQuoteDetail(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = QuoteAdminSer
    queryset = Quote.objects.all()


class AdminUserList(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = UserAdminSer
    queryset = User.objects.annotate(quote_count=Count('quotes')).order_by('-date_joined')


class AdminWaitlistList(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = WaitlistSer
    queryset = WaitlistEntry.objects.all()
