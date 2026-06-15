"""Create/update the Portal B TenantSchedule row on any deployment.

The schedule MIGRATION only creates the empty ``accounts_tenantschedule``
table — it does NOT populate any rows. So on a fresh production database every
tenant still falls back to ``DEFAULT_SCHEDULE`` (Portal A's 2 PM–11 PM shift,
commission ON, no working-hours lock). This command writes the single
TenantSchedule row that turns a given tenant into "Portal B".

Usage (run on the target host, e.g. ``railway run`` or a one-off shell):

    python manage.py setup_portal_b <admin_username>

It is idempotent: running it again updates the existing row in place. It
NEVER touches any other tenant, so Portal A stays byte-for-byte unchanged.

The ``<admin_username>`` must be the tenant ROOT admin account for Portal B
(role=admin, not a superuser). Pass ``--dry-run`` to preview without writing.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import CustomUser, TenantSchedule
from accounts.tenancy import tenant_root


# --- Portal B configuration (single source of truth) -----------------------
# Mon–Sat 09:00–18:00, Sunday off. Check-in opens 08:55, auto-logout 18:30.
# Lunch + Asar namaz are NON-deductible (shown but never deducted). Resume
# becomes available 5 min before each break closes. Commission OFF. Working
# hours enforced (after-hours = view-only + leave application).
PORTAL_B_CONFIG = {
    'work_start': '09:00',
    'work_end': '18:00',
    'checkin_open': '08:55',
    'checkout_max': '18:30',
    'working_days': '0,1,2,3,4,5',  # Mon–Sat
    'breaks': [
        {'start': '13:00', 'end': '14:00', 'label': 'Lunch Break',
         'deductible': False},
        {'start': '17:15', 'end': '17:30', 'label': 'Asar Namaz Break',
         'deductible': False},
    ],
    'break_early_restart_minutes': 5,
    'commission_enabled': False,
    'enforce_working_hours': True,
}


class Command(BaseCommand):
    help = 'Create or update the Portal B TenantSchedule row for one admin.'

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            help='Tenant ROOT admin username for Portal B.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without writing to the database.',
        )

    def handle(self, *args, **options):
        username = options['username']
        dry_run = options['dry_run']

        try:
            user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            raise CommandError(f'No user with username {username!r} exists.')

        if user.is_superuser:
            raise CommandError(
                f'{username!r} is a superuser (global). A TenantSchedule must '
                'point at a tenant ROOT admin, not the global superuser.'
            )

        root = tenant_root(user)
        if root is None:
            raise CommandError(
                f'Could not resolve a tenant root for {username!r}. '
                'Pass the tenant admin account (role=admin).'
            )
        if root.pk != user.pk:
            self.stdout.write(self.style.WARNING(
                f'{username!r} is not a tenant root; using its owner '
                f'{root.username!r} as the Portal B tenant root.'
            ))

        existing = TenantSchedule.objects.filter(admin=root).first()
        verb = 'Would update' if dry_run else 'Updated'
        if existing is None:
            verb = 'Would create' if dry_run else 'Created'

        if dry_run:
            self.stdout.write(self.style.NOTICE(
                f'{verb} Portal B schedule for {root.username!r}:'
            ))
            for k, v in PORTAL_B_CONFIG.items():
                self.stdout.write(f'  {k} = {v!r}')
            return

        obj, created = TenantSchedule.objects.update_or_create(
            admin=root, defaults=PORTAL_B_CONFIG,
        )
        verb = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} Portal B schedule for {root.username!r} '
            f'(commission off, Mon–Sat 09:00–18:00, working-hours enforced).'
        ))
