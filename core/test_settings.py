"""Isolated catalogue tests: in-memory database, no production credentials."""
SECRET_KEY = 'catalogue-tests-only'
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes',
    'rest_framework', 'accounts', 'store',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
AUTH_USER_MODEL = 'accounts.CustomUser'
ROOT_URLCONF = 'store.urls'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
ALLOWED_HOSTS = ['testserver']
MEDIA_URL = '/media/'
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}
