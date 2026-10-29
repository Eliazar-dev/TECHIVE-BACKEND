import hashlib, hmac
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _make(self, email, **extra):
        if not email:
            raise ValueError('Email is required')
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_unusable_password()  # sign-in is OTP / Google only
        user.save(using=self._db)
        return user

    def create_user(self, email, **extra):
        return self._make(email, **extra)

    def create_superuser(self, email, password=None, **extra):
        user = self._make(email, is_staff=True, is_superuser=True, **extra)
        if password:  # lets the superuser also use /django-admin/ with a password
            user.set_password(password)
            user.save()
        return user


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.email


class EmailOTP(models.Model):
    """One-time sign-in code. Only a keyed hash of the code is stored."""
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def digest(email, code):
        msg = f'{email}:{code}'.encode()
        return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
