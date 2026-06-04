import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Idempotently ensure a superuser exists, using credentials from env vars."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")
        email = os.environ.get("ADMIN_EMAIL", "")

        if not username or not password:
            self.stdout.write(
                "ensure_admin: ADMIN_USERNAME / ADMIN_PASSWORD not set, skipping."
            )
            return

        defaults = {
            "email": email,
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
        }
        if hasattr(User, "role"):
            defaults["role"] = "admin"

        user, created = User.objects.get_or_create(username=username, defaults=defaults)

        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        if email:
            user.email = email
        if hasattr(user, "role") and not user.role:
            user.role = "admin"
        user.set_password(password)
        user.save()

        action = "created" if created else "updated"
        self.stdout.write(f"ensure_admin: superuser '{username}' {action}.")
