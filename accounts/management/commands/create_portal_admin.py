"""Create a standalone tenant ADMIN (e.g. the Portal B owner) from the shell.

This exists so a new company admin can be created WITHOUT logging into any
existing admin account and WITHOUT touching any other tenant's data. The new
account is a tenant ROOT (``role='admin'``, ``is_superuser=False``, ``owner``
points at itself), so it is fully isolated: it can only ever see the employees
it creates, and no existing tenant (Portal A) is modified in any way.

Usage (run on the target host, e.g. the Railway Console):

    python manage.py create_portal_admin <username>

You will be prompted for the password TWICE (hidden input via getpass) — the
password is never passed on the command line, so it is not stored in shell
history or visible to anyone. Optional: --email, --first-name, --last-name.

The command refuses to overwrite an existing username, and never creates a
superuser. After it runs, log in at /accounts/login/ as the new admin and
create that company's employees; they will automatically belong to this admin.
"""

from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import CustomUser


class Command(BaseCommand):
    help = 'Create an isolated tenant admin (e.g. Portal B owner) without touching other tenants.'

    def add_arguments(self, parser):
        parser.add_argument('username', help='Username for the new admin.')
        parser.add_argument('--email', default='', help='Optional email.')
        parser.add_argument('--first-name', default='', help='Optional first name.')
        parser.add_argument('--last-name', default='', help='Optional last name.')

    def handle(self, *args, **options):
        username = options['username'].strip()
        if not username:
            raise CommandError('Username may not be empty.')

        if CustomUser.objects.filter(username=username).exists():
            raise CommandError(
                f'A user named {username!r} already exists. Choose another '
                'username (this command will not overwrite existing accounts).'
            )

        # Hidden password entry — never on the command line / shell history.
        password = getpass('New admin password: ')
        confirm = getpass('Confirm password: ')
        if password != confirm:
            raise CommandError('Passwords did not match. Nothing was created.')
        if not password:
            raise CommandError('Password may not be empty. Nothing was created.')
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError('Weak password: ' + '; '.join(exc.messages))

        with transaction.atomic():
            user = CustomUser(
                username=username,
                email=options['email'].strip(),
                first_name=options['first_name'].strip(),
                last_name=options['last_name'].strip(),
                role='admin',
                is_superuser=False,   # NOT a global superuser — a tenant admin.
                is_staff=False,       # No Django admin-site backend access.
                is_active=True,
            )
            user.set_password(password)
            user.save()
            # A tenant root owns itself (matches the model's convention) so it
            # forms its own isolated tenant boundary.
            user.owner = user
            user.save(update_fields=['owner'])

        self.stdout.write(self.style.SUCCESS(
            f"Created tenant admin {username!r} (role=admin, superuser=False, "
            f"owns itself). Log in at /accounts/login/ and create this "
            f"company's employees under it."
        ))
