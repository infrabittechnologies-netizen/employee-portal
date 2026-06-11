from pathlib import Path
from decouple import config
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-employee-portal-dev-key-abc123xyz')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost').split(',') + ['*', 'portal.infrabit.tech']

CSRF_TRUSTED_ORIGINS = [
    'https://portal.infrabit.tech',
    'https://*.up.railway.app',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'crispy_forms',
    'crispy_bootstrap5',
    'accounts',
    'attendance',
    'leaves',
    'salary',
    'performance',
    'holidays',
    'notifications_app',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Runs after auth so it knows the role: only ordinary employees are
    # limited to the approved office IPs; admins can sign in from anywhere.
    'employee_portal.middleware.IPWhitelistMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'employee_portal.middleware.DesktopOnlyMiddleware',
    'employee_portal.middleware.EmployeeAutoLogoutMiddleware',
]

# ---------------------------------------------------------------------------
# IP allow-list — the portal is usable ONLY from these approved public IPs.
# Any other IP gets a professional "access blocked" page on every URL
# (including login). Override on Railway via the PORTAL_ALLOWED_IPS env var
# (comma-separated; single IPs or CIDR ranges, IPv4/IPv6).
#
# Defaults below: two office IPs + the owner's laptop.
# Leave the list non-empty; an empty list disables the guard (fail-open) to
# avoid accidentally locking everyone out.
# ---------------------------------------------------------------------------
PORTAL_ALLOWED_IPS = [
    ip.strip() for ip in config(
        'PORTAL_ALLOWED_IPS',
        default='203.96.170.34,39.34.172.108,154.57.217.25',
    ).split(',') if ip.strip()
]

# Which X-Forwarded-For entry is the real client. Default ('auto') walks the
# chain from the right and picks the last PUBLIC IP (spoof-resistant on a
# single-proxy platform like Railway). Set to an integer index only if a
# platform needs an explicit position (e.g. -2).
_xff_idx = str(config('PORTAL_IP_XFF_INDEX', default='auto')).strip()
PORTAL_IP_XFF_INDEX = int(_xff_idx) if _xff_idx not in ('', 'auto') else None

ROOT_URLCONF = 'employee_portal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'notifications_app.context_processors.notifications_count',
            ],
        },
    },
]

WSGI_APPLICATION = 'employee_portal.wsgi.application'

DATABASE_URL = config('DATABASE_URL', default=None)
if DATABASE_URL:
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Karachi'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.CustomUser'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

WORK_START_TIME = '09:00'
LATE_ARRIVAL_THRESHOLD = '09:30'
WORK_END_TIME = '18:00'
WORKING_DAYS_PER_MONTH = 26
