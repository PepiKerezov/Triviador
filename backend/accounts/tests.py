from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from .models import Profile

User = get_user_model()


class AuthenticationApiTests(APITestCase):
	def setUp(self):
		self.registration_data = {
			'username': 'player_one',
			'email': 'player@example.com',
			'nickname': 'MountainKnight',
			'password': 'example-password',
			'password_confirm': 'example-password',
		}

	def register(self, **overrides):
		data = {**self.registration_data, **overrides}
		return self.client.post('/api/auth/register/', data, format='json')

	def login(self):
		return self.client.post(
			'/api/auth/login/',
			{'username': 'player_one', 'password': 'example-password'},
			format='json',
		)

	def test_registration_creates_hashed_user_and_profile_without_password(self):
		response = self.register()

		self.assertEqual(response.status_code, status.HTTP_201_CREATED)
		user = User.objects.get(username='player_one')
		self.assertTrue(user.check_password('example-password'))
		self.assertEqual(user.profile.nickname, 'MountainKnight')
		self.assertEqual(user.profile.avatar_key, 'knight-1')
		self.assertNotIn('password', response.data)
		self.assertNotIn('password_confirm', response.data)

	def test_invalid_registration_returns_errors_without_creating_user(self):
		self.register()
		user_count = User.objects.count()

		cases = (
			{'username': 'player_one'},
			{'email': 'player@example.com'},
			{'nickname': 'MountainKnight'},
			{'password_confirm': 'different-password'},
		)
		for overrides in cases:
			with self.subTest(overrides=overrides):
				response = self.register(**overrides)
				self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
				self.assertIn('errors', response.data)
		self.assertEqual(User.objects.count(), user_count)

	def test_login_creates_session_and_allows_me(self):
		self.register()

		response = self.login()
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertIn('sessionid', self.client.cookies)

		me_response = self.client.get('/api/auth/me/')
		self.assertEqual(me_response.status_code, status.HTTP_200_OK)
		self.assertEqual(me_response.data['username'], 'player_one')

	def test_invalid_login_does_not_authenticate(self):
		self.register()

		response = self.client.post(
			'/api/auth/login/',
			{'username': 'player_one', 'password': 'wrong-password'},
			format='json',
		)

		self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertNotIn('sessionid', self.client.cookies)
		self.assertIn('errors', response.data)
		self.assertEqual(
			self.client.get('/api/auth/me/').status_code,
			status.HTTP_403_FORBIDDEN,
		)

	def test_me_requires_authentication_and_returns_current_user(self):
		self.assertEqual(
			self.client.get('/api/auth/me/').status_code,
			status.HTTP_403_FORBIDDEN,
		)
		self.register()
		self.login()

		response = self.client.get('/api/auth/me/')

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data['email'], 'player@example.com')

	def test_profile_update_only_changes_allowed_fields(self):
		self.register()
		self.login()

		response = self.client.patch(
			'/api/auth/me/',
			{'nickname': 'NewKnight', 'avatar_key': 'knight-3'},
			format='json',
		)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
		profile = Profile.objects.get(nickname='NewKnight')
		self.assertEqual(profile.avatar_key, 'knight-3')

		protected_response = self.client.patch(
			'/api/auth/me/',
			{'is_staff': True},
			format='json',
		)
		self.assertEqual(protected_response.status_code, status.HTTP_400_BAD_REQUEST)
		self.assertFalse(User.objects.get(username='player_one').is_staff)

	def test_logout_ends_session(self):
		self.register()
		self.login()

		response = self.client.post('/api/auth/logout/', format='json')

		self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
		self.assertEqual(
			self.client.get('/api/auth/me/').status_code,
			status.HTTP_403_FORBIDDEN,
		)

	def test_csrf_is_required_for_authenticated_unsafe_request(self):
		client = APIClient(enforce_csrf_checks=True)
		user = User.objects.create_user(
			username='csrf_player',
			email='csrf@example.com',
			password='example-password',
		)
		Profile.objects.create(user=user, nickname='CsrfKnight')
		self.assertTrue(client.login(username='csrf_player', password='example-password'))

		response = client.patch(
			'/api/auth/me/',
			{'nickname': 'BlockedKnight'},
			format='json',
		)
		self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

		csrf_response = client.get('/api/auth/csrf/')
		self.assertEqual(csrf_response.status_code, status.HTTP_204_NO_CONTENT)
		csrf_token = client.cookies['csrftoken'].value
		response = client.patch(
			'/api/auth/me/',
			{'nickname': 'AllowedKnight'},
			format='json',
			HTTP_X_CSRFTOKEN=csrf_token,
		)
		self.assertEqual(response.status_code, status.HTTP_200_OK)
