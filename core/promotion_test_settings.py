from .test_settings import *
INSTALLED_APPS = INSTALLED_APPS + ['orders', 'payments', 'mails']
ROOT_URLCONF = 'core.promotion_test_urls'
RAZORPAY_KEY_ID = 'test-key'
DEFAULT_FROM_EMAIL = 'test@example.invalid'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
