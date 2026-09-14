"""
Django settings for ceg_project.
K-pop Group Order (CEG) Management Platform.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente de .env se existir
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-kr6krlgapr$0xjn!hb-uio%p=5pypxe^sk3t9$y%(uzc0^y4fw')

DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

# Domínios Permitidos
allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '*')
if allowed_hosts_env and allowed_hosts_env.strip() != '*':
    parsed_hosts = []
    for h in allowed_hosts_env.split(','):
        h = h.strip()
        if not h:
            continue
        parsed_hosts.append(h)
        if h.startswith('*.'):
            parsed_hosts.append(h[1:])  # '.onrender.com'
            parsed_hosts.append(h[2:])  # 'onrender.com'
    parsed_hosts.extend(['.onrender.com', 'localhost', '127.0.0.1'])
    ALLOWED_HOSTS = list(set(parsed_hosts))
else:
    ALLOWED_HOSTS = ['*']

# Proteção CSRF para conexões seguras (HTTPS em produção)
csrf_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if csrf_origins_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_env.split(',') if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        'https://*.onrender.com',
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'http://150.136.166.17',
        'https://150.136.166.17',
        'http://150.136.166.17:8000',
        'http://*.sslip.io',
        'https://*.sslip.io',
    ]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party apps
    'rest_framework',
    'storages',
    # Local apps
    'apps.groups',
    'apps.cegs',
    'apps.participants',
    'apps.auth_otp',
    'apps.analytics',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ceg_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.participants.context_processors.current_participant',
            ],
        },
    },
]

WSGI_APPLICATION = 'ceg_project.wsgi.application'

# Banco de Dados (PostgreSQL no Render / SQLite local)
database_url = os.getenv('DATABASE_URL')
if database_url:
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.config(
            default=database_url,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {
                'timeout': 20,
            }
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Configurações de Internacionalização e Timezone
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# Static Files (WhiteNoise com compressão e hash para cache)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media Storage (Cloudflare R2 / AWS S3 ou Local)
USE_R2 = os.getenv('USE_R2', 'False').lower() in ('true', '1', 'yes') or bool(
    os.getenv('R2_BUCKET_NAME') or os.getenv('AWS_STORAGE_BUCKET_NAME')
)

if USE_R2:
    AWS_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID') or os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.getenv('R2_BUCKET_NAME') or os.getenv('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL') or os.getenv('AWS_S3_ENDPOINT_URL')
    AWS_S3_CUSTOM_DOMAIN = os.getenv('R2_CUSTOM_DOMAIN') or os.getenv('AWS_S3_CUSTOM_DOMAIN')
    AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', 'auto')
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False

    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/"
    elif AWS_S3_ENDPOINT_URL and AWS_STORAGE_BUCKET_NAME:
        MEDIA_URL = f"{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/"
    else:
        MEDIA_URL = '/media/'

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# Configurações WhatsApp Gateway
# Opções de WHATSAPP_PROVIDER: 'console', 'evolution', 'zapi'
WHATSAPP_PROVIDER = os.getenv('WHATSAPP_PROVIDER', 'console')
EVOLUTION_API_URL = os.getenv('EVOLUTION_API_URL', 'http://localhost:8080')
EVOLUTION_API_KEY = os.getenv('EVOLUTION_API_KEY', '')
EVOLUTION_INSTANCE_NAME = os.getenv('EVOLUTION_INSTANCE_NAME', 'ceg-bot')

ZAPI_INSTANCE_ID = os.getenv('ZAPI_INSTANCE_ID', '')
ZAPI_TOKEN = os.getenv('ZAPI_TOKEN', '')
ZAPI_CLIENT_TOKEN = os.getenv('ZAPI_CLIENT_TOKEN', '')
