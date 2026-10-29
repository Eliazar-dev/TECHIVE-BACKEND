from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from .models import User


@override_settings(GOOGLE_CLIENT_ID='cid')
class GoogleTests(APITestCase):
    def _post(self, info=None, exc=None):
        with mock.patch('accounts.views.id_token.verify_oauth2_token', return_value=info, side_effect=exc):
            return self.client.post('/api/auth/google/', {'credential': 'tok'}, format='json')

    def test_creates_user_from_verified_google_account(self):
        r = self._post({'email': 'G@Example.com', 'email_verified': True, 'given_name': 'Gina', 'family_name': 'Lee'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['user']['first_name'], 'Gina')
        self.assertTrue(User.objects.filter(email='g@example.com').exists())

    @override_settings(ADMIN_EMAILS=['g@example.com'])
    def test_admin_email_promoted_via_google(self):
        r = self._post({'email': 'g@example.com', 'email_verified': True})
        self.assertTrue(r.data['user']['is_staff'])

    def test_unverified_email_and_bad_token_rejected(self):
        self.assertEqual(self._post({'email': 'x@y.com', 'email_verified': False}).status_code, 400)
        self.assertEqual(self._post(exc=ValueError).status_code, 400)
        self.assertFalse(User.objects.exists())
