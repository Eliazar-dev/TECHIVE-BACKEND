import re
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import EmailOTP, User
from core.models import Quote, WaitlistEntry


def login(client, email='client@example.com'):
    client.post('/api/auth/otp/request/', {'email': email}, format='json')
    code = re.search(r'code is (\d{6})', mail.outbox[-1].body).group(1)
    r = client.post('/api/auth/otp/verify/', {'email': email, 'code': code}, format='json')
    assert r.status_code == 200, r.content
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + r.data['access'])
    return r.data


class OTPTests(APITestCase):
    def test_full_otp_login_creates_user(self):
        data = login(self.client)
        self.assertEqual(data['user']['email'], 'client@example.com')
        self.assertFalse(data['user']['is_staff'])
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 200)

    def test_invalid_email(self):
        self.assertEqual(self.client.post('/api/auth/otp/request/', {'email': 'nope'}, format='json').status_code, 400)

    def test_resend_cooldown(self):
        self.client.post('/api/auth/otp/request/', {'email': 'a@example.com'}, format='json')
        r = self.client.post('/api/auth/otp/request/', {'email': 'a@example.com'}, format='json')
        self.assertEqual(r.status_code, 429)

    def test_wrong_code_and_lockout(self):
        self.client.post('/api/auth/otp/request/', {'email': 'a@example.com'}, format='json')
        real = re.search(r'code is (\d{6})', mail.outbox[-1].body).group(1)
        wrong = '000000' if real != '000000' else '111111'
        for _ in range(6):
            self.assertEqual(self.client.post('/api/auth/otp/verify/', {'email': 'a@example.com', 'code': wrong}, format='json').status_code, 400)
        # locked: even the right code no longer works
        self.assertEqual(self.client.post('/api/auth/otp/verify/', {'email': 'a@example.com', 'code': real}, format='json').status_code, 400)
        self.assertFalse(User.objects.filter(email='a@example.com').exists())

    def test_code_is_single_use_and_hashed(self):
        self.client.post('/api/auth/otp/request/', {'email': 'a@example.com'}, format='json')
        code = re.search(r'code is (\d{6})', mail.outbox[-1].body).group(1)
        self.assertNotIn(code, EmailOTP.objects.get().code_hash)
        ok = self.client.post('/api/auth/otp/verify/', {'email': 'a@example.com', 'code': code}, format='json')
        again = self.client.post('/api/auth/otp/verify/', {'email': 'a@example.com', 'code': code}, format='json')
        self.assertEqual((ok.status_code, again.status_code), (200, 400))

    @override_settings(ADMIN_EMAILS=['boss@example.com'])
    def test_admin_email_is_promoted(self):
        self.assertTrue(login(self.client, 'boss@example.com')['user']['is_staff'])

    def test_google_not_configured(self):
        self.assertEqual(self.client.post('/api/auth/google/', {'credential': 'x'}, format='json').status_code, 503)


class QuoteAndAdminTests(APITestCase):
    def test_quote_requires_sign_in(self):
        self.assertEqual(self.client.post('/api/quotes/', {'message': 'hi'}, format='json').status_code, 401)

    def test_signed_in_user_can_request_quote(self):
        login(self.client)
        r = self.client.post('/api/quotes/', {'service': 'Web Development', 'budget': '50k', 'message': 'Need a site', 'phone': '0700'}, format='json')
        self.assertEqual(r.status_code, 201)
        q = Quote.objects.get()
        self.assertEqual((q.email, q.status), ('client@example.com', 'new'))
        self.assertTrue(any('New quote request' in m.subject for m in mail.outbox))

    def test_blank_name_falls_back_to_email_prefix(self):
        login(self.client)
        r = self.client.post('/api/quotes/', {'name': '', 'phone': '', 'service': '', 'budget': '', 'message': 'Hi'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Quote.objects.get().name, 'client')

    def test_quote_needs_message(self):
        login(self.client)
        self.assertEqual(self.client.post('/api/quotes/', {'service': 'x'}, format='json').status_code, 400)

    def test_waitlist_is_idempotent_and_public(self):
        for _ in range(2):
            self.assertEqual(self.client.post('/api/academy/waitlist/', {'email': 'Z@Example.com', 'course': 'Python'}, format='json').status_code, 201)
        self.assertEqual(WaitlistEntry.objects.count(), 1)

    def test_admin_api_blocked_for_normal_users(self):
        self.assertEqual(self.client.get('/api/admin/stats/').status_code, 401)
        login(self.client)
        for p in ('stats', 'quotes', 'users', 'waitlist'):
            self.assertEqual(self.client.get(f'/api/admin/{p}/').status_code, 403, p)

    @override_settings(ADMIN_EMAILS=['boss@example.com'])
    def test_admin_can_manage_quotes(self):
        client_user = User.objects.create_user('c@example.com')
        q = Quote.objects.create(user=client_user, name='C', email='c@example.com', message='m', service='SEO')
        login(self.client, 'boss@example.com')
        self.assertEqual(self.client.get('/api/admin/stats/').data['quotes_total'], 1)
        self.assertEqual(self.client.get('/api/admin/quotes/?status=new').data['count'], 1)
        r = self.client.patch(f'/api/admin/quotes/{q.pk}/', {'status': 'won', 'notes': 'signed', 'message': 'hacked'}, format='json')
        self.assertEqual(r.status_code, 200)
        q.refresh_from_db()
        self.assertEqual((q.status, q.notes, q.message), ('won', 'signed', 'm'))  # message is read-only
        self.assertEqual(self.client.get('/api/admin/users/').status_code, 200)


class StatusTests(APITestCase):
    def test_health_reports_ok_and_db_connected(self):
        r = self.client.get('/api/health/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()['status'], r.json()['database']), ('ok', 'connected'))
        self.assertIn('uptime_seconds', r.json())

    def test_status_page_is_html_and_not_cached(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Techive API', r.content)
        self.assertEqual(r['Cache-Control'], 'no-store')
