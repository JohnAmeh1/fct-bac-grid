"""
Django settings for Digital_Tenement_Rate_Management_System project.
...
"""

import os
from pathlib import Path
import dj_database_url


BASE_DIR = Path(__file__).resolve().parent.parent

# SECRET_KEY = 'django-insecure-b)09@+xjhvhy#q4o_3a0vvoe(q3nry9xhu!9(qfi-47%-ail01'
# SECRET_KEY = os.environ.get('SECRET_KEY')



SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-b)09@+xjhvhy#q4o_3a0vvoe(q3nry9xhu!9(qfi-47%-ail01'
)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# DEBUG = False

ALLOWED_HOSTS = ['*']

DEBUG = True

# ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '.ngrok-free.app']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'tenement',
    # 'anymail',  # removed – using Django's built-in SMTP backend with Mailtrap
]

# ====================================================================
# Email Configuration – Mailtrap Live SMTP
# ====================================================================
EMAIL_BACKEND    = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST       = 'live.smtp.mailtrap.io'
EMAIL_PORT       = 587
EMAIL_USE_TLS    = True   # STARTTLS on port 587
EMAIL_USE_SSL    = False
EMAIL_HOST_USER  = 'api'
EMAIL_HOST_PASSWORD = '73a133a1dc2c01f8e4a3de6f8e83e63f'
DEFAULT_FROM_EMAIL = 'Bwari Tenement <customercare@bwari-revenue.com>'

# EMAIL_BACKEND    = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST       = 'sandbox.smtp.mailtrap.io'   # ← sandbox, not live
# EMAIL_PORT       = 2525
# EMAIL_USE_TLS    = True
# EMAIL_USE_SSL    = False
# EMAIL_HOST_USER  = '38901b8138fc7d'
# EMAIL_HOST_PASSWORD = 'ca3758827d7689'
# DEFAULT_FROM_EMAIL = 'Bwari Tenement <hello@bwari-revenue.com>'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
]

# Custom CSRF failure view
CSRF_FAILURE_VIEW = 'tenement.views.csrf_failure'

ROOT_URLCONF = 'Digital_Tenement_Rate_Management_System.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'tenement' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'Digital_Tenement_Rate_Management_System.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'bac-grid',
        'USER': 'postgres',
        'PASSWORD': '221005',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'tenement_db',
#         'USER': 'postgres',
#         'PASSWORD': '221005',
#         'HOST': 'localhost',
#         'PORT': '5432',
#     }
# }

# DATABASE_URL = "postgresql://neondb_owner:npg_5NRoX0npJyKs@ep-steep-shape-am1gc0cs-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# DATABASES = {
#     "default": dj_database_url.parse(
#         DATABASE_URL,
#         conn_max_age=60,
#     )
# }

CSRF_TRUSTED_ORIGINS = ['https://*.ngrok-free.app']

PAYSTACK_SECRET_KEY = 'sk_test_17f3c3ed7cf5147fba18be087cf1a4192dfd67fe'
PAYSTACK_PUBLIC_KEY = 'pk_test_fdeb97ce15dc119e28cc589fcb24fac669b14f81'
PAYSTACK_CALLBACK_URL = 'http://yourdomain.com/payments/verify/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG:   'debug',
    messages.INFO:    'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR:   'error',
}