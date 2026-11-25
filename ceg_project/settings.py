"""
Django settings for ceg_project.
K-pop Group Order (CEG) Management Platform.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# Carrega variáveis de ambiente de .env se existir
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in ('true', '1', 'yes', 'on')


# Seguro por padrão: desenvolvimento local precisa de DEBUG=True no .env (ver .env.example).
DEBUG = env_bool('DEBUG', False)

SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("SECRET_KEY é obrigatória quando DEBUG=False.")
    SECRET_KEY = 'django-insecure-dev-only-key-nao-use-em-producao'

# Criptografia de dados pessoais (apps/core/crypto.py). Chave SEPARADA da SECRET_KEY.
# Aceita várias chaves separadas por vírgula (a primeira criptografa) para rotação.
# Gerar: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# PERDER ESTA CHAVE = PERDER OS ENDEREÇOS. Guarde uma cópia fora do servidor.
FIELD_ENCRYPTION_KEYS = [k.strip() for k in os.getenv('FIELD_ENCRYPTION_KEY', '').split(',') if k.strip()]
if not FIELD_ENCRYPTION_KEYS:
    if not DEBUG:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY é obrigatória quando DEBUG=False.")
    import base64 as _b64, hashlib as _hashlib
    # Apenas desenvolvimento/testes: chave derivada da SECRET_KEY local.
    FIELD_ENCRYPTION_KEYS = [_b64.urlsafe_b64encode(_hashlib.sha256(
        ('field-encryption-dev:' + SECRET_KEY).encode()).digest()).decode()]

# Retenção de dados pessoais (comando purge_personal_data)
PII_RETENTION_DAYS = int(os.getenv('PII_RETENTION_DAYS', 180))  # endereço após a entrega
OTP_RETENTION_DAYS = int(os.getenv('OTP_RETENTION_DAYS', 30))

# Domínios Permitidos (Host header). Em produção nunca aceita '*': sem ALLOWED_HOSTS no
# .env, vale a lista dos domínios servidos pelo Caddy.
PRODUCTION_HOSTS = ['valcegs.duckdns.org', '129.213.164.99.sslip.io']
allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '').strip()
if allowed_hosts_env and allowed_hosts_env != '*':
    parsed_hosts = []
    for h in allowed_hosts_env.split(','):
        h = h.strip()
        if not h:
            continue
        parsed_hosts.append(h)
        if h.startswith('*.'):
            parsed_hosts.append(h[1:])  # '.exemplo.com' cobre subdomínios
    ALLOWED_HOSTS = sorted(set(parsed_hosts + ['localhost', '127.0.0.1']))
elif DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = PRODUCTION_HOSTS + ['localhost', '127.0.0.1']

# Proteção CSRF para conexões seguras (HTTPS em produção)
csrf_origins_env = os.getenv('CSRF_TRUSTED_ORIGINS', '')
if csrf_origins_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_env.split(',') if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        'https://valcegs.duckdns.org',
        'https://*.onrender.com',
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'http://129.213.164.99',
        'https://129.213.164.99',
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
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    'storages',
    # Local apps
    'apps.groups',
    'apps.cegs',
    'apps.participants',
    'apps.auth_otp',
    'apps.analytics',
    'apps.core',
    'apps.goms',
    'apps.pagamentos',
    'apps.conversas',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'apps.core.security_headers.SecurityHeadersMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'apps.core.admin_throttle.AdminLoginThrottleMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'apps.core.two_factor.StaffTwoFactorMiddleware',
    'apps.goms.access.GomStaffMiddleware',
    'apps.cegs.middleware.UploadSizeExceptionMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ceg_project.urls'

LOGIN_URL = '/entrar/'  # login do backoffice (staff e membros de GOM)

# 2FA (TOTP) obrigatório para o backoffice — política em apps/core/two_factor.py.
# Não há variável de ambiente para desligar: perda do celular -> `manage.py reset_2fa <usuario>`.
STAFF_2FA_REQUIRED = True
OTP_TOTP_ISSUER = 'ValCegs'
# Sessão de staff verificada expira em 12h (joiners seguem SESSION_COOKIE_AGE).
STAFF_SESSION_AGE = int(os.getenv('STAFF_SESSION_AGE', 60 * 60 * 12))
TEST_RUNNER = 'apps.core.test_runner.ProjectTestRunner'

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
                'apps.core.context_processors.frontend',
                'apps.goms.context_processors.gom_context',
            ],
            'builtins': ['apps.core.templatetags.json_embed', 'apps.core.templatetags.images', 'django.templatetags.static'],
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

# Frontend: 'build' usa os arquivos gerados por `npm run build` (feito no Docker):
# static/css/tailwind.css e static/js/lucide-subset.min.js. 'dev' usa o Play CDN do Tailwind
# e o Lucide completo (static/vendor), sem precisar de Node — só para desenvolvimento.
FRONTEND_MODE = os.getenv('FRONTEND_MODE', 'dev' if DEBUG else 'build')
if FRONTEND_MODE not in ('build', 'dev'):
    raise ImproperlyConfigured("FRONTEND_MODE deve ser 'build' ou 'dev'.")
# Emergência: True envia a CSP só como relatório (não bloqueia nada).
CSP_REPORT_ONLY = env_bool('CSP_REPORT_ONLY', False)

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
    # Nenhuma view usa DRF hoje; se alguma for criada, nasce fechada (só staff).
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAdminUser',
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

# Configurações de Upload de Imagens e Arquivos
# Definido para 10 MB para comportar o limite de 5 MB por foto com folga para multipart/POST
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000  # Permite formulários grandes de alocação em lote

# ==============================================================================
# Segurança HTTP (produção). O redirect HTTP -> HTTPS é feito pelo Caddy.
# ==============================================================================
# O Caddy informa o protocolo original; sem isso o Django acha que tudo é HTTP.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', 60 * 60 * 24 * 14))  # 14 dias
# CSRF_COOKIE_HTTPONLY fica False: scripts do front leem o cookie csrftoken via getCookie().
CSRF_COOKIE_SAMESITE = 'Lax'

# Cookies só trafegam por HTTPS fora do DEBUG (SECURE_COOKIES=False apenas para emergências).
SESSION_COOKIE_SECURE = env_bool('SECURE_COOKIES', not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# HSTS: o navegador passa a exigir HTTPS. Comece baixo e aumente após validar.
SECURE_HSTS_SECONDS = 0 if DEBUG else int(os.getenv('SECURE_HSTS_SECONDS', 60 * 60 * 24 * 30))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Avisos do `check --deploy` aceitos conscientemente (o CI falha em qualquer outro):
SILENCED_SYSTEM_CHECKS = [
    'security.W005',  # HSTS includeSubDomains: não há subdomínios próprios
    'security.W008',  # SECURE_SSL_REDIRECT: o redirect HTTP -> HTTPS é feito pelo Caddy
    'security.W021',  # HSTS preload: compromisso de longo prazo, avaliar depois
]

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# ==============================================================================
# Cache compartilhado (Redis no Docker; memória local em dev/testes).
# Usado pelo rate limit do login do admin, que precisa valer entre os workers.
# ==============================================================================
REDIS_URL = os.getenv('REDIS_URL', '')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'KEY_PREFIX': 'valcegs',
        }
    }
    # Sessão lida do Redis (gravada também no banco): evita uma query por requisição.
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# ==============================================================================
# Logging: eventos de segurança vão para o stdout do container (docker logs).
# ==============================================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'loggers': {
        'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'security': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'apps.auth_otp': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
