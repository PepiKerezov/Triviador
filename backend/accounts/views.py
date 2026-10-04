from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ProfileSerializer, RegistrationSerializer, UserSerializer


def validation_error_response(serializer):
	return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
@ensure_csrf_cookie
def csrf_token(request):
	get_token(request)
	return Response(status=status.HTTP_204_NO_CONTENT)


class RegisterView(APIView):
	permission_classes = (permissions.AllowAny,)

	def post(self, request):
		serializer = RegistrationSerializer(data=request.data)
		if not serializer.is_valid():
			return validation_error_response(serializer)
		user = serializer.save()
		return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
	permission_classes = (permissions.AllowAny,)

	def post(self, request):
		username = request.data.get('username')
		password = request.data.get('password')
		user = authenticate(request, username=username, password=password)
		if user is None:
			return Response(
				{'errors': {'non_field_errors': ['Invalid credentials.']}},
				status=status.HTTP_400_BAD_REQUEST,
			)
		login(request, user)
		return Response(UserSerializer(user).data)


class LogoutView(APIView):
	permission_classes = (permissions.IsAuthenticated,)

	def post(self, request):
		logout(request)
		return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
	permission_classes = (permissions.IsAuthenticated,)

	def get(self, request):
		return Response(UserSerializer(request.user).data)

	def patch(self, request):
		allowed_fields = {'nickname', 'avatar_key'}
		forbidden_fields = set(request.data) - allowed_fields
		if forbidden_fields:
			return Response(
				{
					'errors': {
						field: ['This field is not allowed.']
						for field in forbidden_fields
					}
				},
				status=status.HTTP_400_BAD_REQUEST,
			)
		serializer = ProfileSerializer(request.user.profile, data=request.data, partial=True)
		if not serializer.is_valid():
			return validation_error_response(serializer)
		serializer.save()
		return Response(UserSerializer(request.user).data)
