from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
	email = models.EmailField(unique=True)


class Profile(models.Model):
	AVATAR_KEYS = (
		'knight-1',
		'knight-2',
		'knight-3',
		'knight-4',
	)

	user = models.OneToOneField(
		User,
		on_delete=models.CASCADE,
		related_name='profile',
	)
	nickname = models.CharField(max_length=30, unique=True)
	avatar_key = models.CharField(max_length=30, default='knight-1')

	def __str__(self):
		return self.nickname
