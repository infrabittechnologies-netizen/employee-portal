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
    help = 'Create or update the Portal B TenantSchedule row(s) for the named users.'

    def add_arguments(self, parser):
        parser.add_argument(
            'usernames', nargs='+',
            help=(
                'One or more usernames to put on the Portal B schedule. Each '
                'is resolved to its schedule-root the same way the app does '
                '(tenant_root(user) or the user itself when it has no owner).'
            ),
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without writing to the database.',
        )

    def _resolve_root(self, user):
        """Mirror attendance.schedule.resolve_schedule: the schedule key is
        ``tenant_root(user) or user`` — so a user with no owner is its own
        schedule-root (this is how the infrabit deployment is structured)."""
        return tenant_root(user) or user

    def handle(self, *args, **options):
        usernames = options['usernames']
        dry_run = options['dry_run']

        # Resolve + validate ALL targets up front so a bad name aborts before
        # any write. We never touch a user that isn't explicitly named here.
        targets = []  # (input_username, schedule_root_user)
        for username in usernames:
            try:
                user = CustomUser.objects.get(username=username)
            except CustomUser.DoesNotExist:
                raise CommandError(f'No user with username {username!r} exists.')
            if user.is_superuser:
                raise CommandError(
                    f'{username!r} is a superuser (global). Superusers always '
                    'use the DEFAULT schedule and must not be put on Portal B.'
                )
            root = self._resolve_root(user)
            if root is None:
                raise CommandError(
                    f'Could not resolve a schedule-root for {username!r}.'
                )
            targets.append((username, root))

        if dry_run:
            self.stdout.write(self.style.NOTICE(
                'DRY RUN — no changes will be written.'
            ))
            for username, root in targets:
                exists = TenantSchedule.objects.filter(admin=root).exists()
                verb = 'Would update' if exists else 'Would create'
                note = '' if root.username == username else f' (root: {root.username!r})'
                self.stdout.write(f'  {verb} Portal B schedule for {username!r}{note}')
            self.stdout.write('\nConfig that will be applied:')
            for k, v in PORTAL_B_CONFIG.items():
                self.stdout.write(f'  {k} = {v!r}')
            return

        for username, root in targets:
            _obj, created = TenantSchedule.objects.update_or_create(
                admin=root, defaults=PORTAL_B_CONFIG,
            )
            verb = 'Created' if created else 'Updated'
            note = '' if root.username == username else f' (root: {root.username!r})'
            self.stdout.write(self.style.SUCCESS(
                f'{verb} Portal B schedule for {username!r}{note}'
            ))
        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(targets)} user(s) on Portal B '
            '(commission off, Mon–Sat 09:00–18:00, working-hours enforced).'
        ))
