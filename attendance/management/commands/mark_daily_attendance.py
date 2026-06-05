"""
Daily attendance finaliser.

For a given working day, this command looks at every active employee who did
NOT check in and assigns a status automatically:

  * Approved leave covering that day  ->  status = 'leave'
  * No approved leave                 ->  status = 'absent'

Days that are skipped (no record created):
  * Weekends (Sat / Sun)
  * Company holidays
  * Employees who already have a check-in for the day (they worked)
  * Records an admin manually set to present / late / half_day (intent respected)

The command is idempotent — running it again for the same date is safe.

Usage:
    python manage.py mark_daily_attendance                # finalise today
    python manage.py mark_daily_attendance --date 2026-06-04
    python manage.py mark_daily_attendance --days-back 1  # finalise yesterday
    python manage.py mark_daily_attendance --dry-run      # report only, no writes

Intended to be scheduled once a day, shortly after the shift ends (e.g. 23:30 PKT),
or just after midnight with --days-back 1.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from attendance.models import Attendance
from attendance.schedule import is_weekend
from holidays.models import Holiday
from leaves.models import LeaveApplication

User = get_user_model()

# Statuses that mean the employee was genuinely present / handled manually.
# We never overwrite these from the auto-rule.
PROTECTED_STATUSES = {'present', 'late', 'half_day'}


class Command(BaseCommand):
    help = (
        "Finalise a working day's attendance: mark non-checked-in employees as "
        "'leave' (if an approved leave covers the day) or 'absent' otherwise."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='Target date as YYYY-MM-DD (defaults to today, local time).',
        )
        parser.add_argument(
            '--days-back',
            type=int,
            default=0,
            help='Finalise N days before today (e.g. 1 = yesterday). Ignored if --date is given.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would change without writing to the database.',
        )

    def handle(self, *args, **options):
        target_date = self._resolve_date(options)
        dry_run = options['dry_run']

        # 1. Skip weekends entirely.
        if is_weekend(target_date):
            self.stdout.write(
                self.style.WARNING(
                    f'{target_date} is a weekend — nothing to finalise.'
                )
            )
            return

        # 2. Skip company holidays.
        if Holiday.objects.filter(date=target_date).exists():
            self.stdout.write(
                self.style.WARNING(
                    f'{target_date} is a company holiday — nothing to finalise.'
                )
            )
            return

        # Employees expected to mark attendance: active users who are not
        # admins/superusers (admins manage the team and do not check in).
        employees = (
            User.objects.filter(is_active=True)
            .exclude(role='admin')
            .exclude(is_superuser=True)
        )

        # Pre-fetch approved leaves covering the target date for these employees.
        approved_emp_ids = set(
            LeaveApplication.objects.filter(
                status='approved',
                from_date__lte=target_date,
                to_date__gte=target_date,
                employee__in=employees,
            ).values_list('employee_id', flat=True)
        )

        # Existing attendance for the day, keyed by employee id.
        existing = {
            a.employee_id: a
            for a in Attendance.objects.filter(date=target_date, employee__in=employees)
        }

        marked_absent = 0
        marked_leave = 0
        skipped_worked = 0
        skipped_protected = 0

        with transaction.atomic():
            for emp in employees:
                record = existing.get(emp.id)

                # Already checked in -> they worked, leave untouched.
                if record and record.check_in:
                    skipped_worked += 1
                    continue

                # Admin manually set present/late/half_day (no check-in) -> respect it.
                if record and record.status in PROTECTED_STATUSES:
                    skipped_protected += 1
                    continue

                on_leave = emp.id in approved_emp_ids
                new_status = 'leave' if on_leave else 'absent'

                # Idempotent: skip if already in the correct auto-status.
                if record and record.status == new_status:
                    continue

                if on_leave:
                    marked_leave += 1
                    note = 'Auto-marked: on approved leave (no check-in).'
                else:
                    marked_absent += 1
                    note = 'Auto-marked absent (no check-in, no approved leave).'

                label = emp.get_full_name() or emp.username
                self.stdout.write(f'  {new_status.upper():7} {label}')

                if dry_run:
                    continue

                if record is None:
                    record = Attendance(employee=emp, date=target_date)
                record.status = new_status
                record.check_in = None
                record.check_out = None
                record.work_hours = Decimal('0.00')
                record.is_late = False
                record.ip_address = None
                if not record.notes:
                    record.notes = note
                record.save()

            if dry_run:
                transaction.set_rollback(True)

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(
                f'{prefix}{target_date}: {marked_absent} marked absent, '
                f'{marked_leave} marked on leave. '
                f'(Skipped {skipped_worked} who worked, '
                f'{skipped_protected} manually set.)'
            )
        )

    def _resolve_date(self, options):
        if options['date']:
            try:
                return datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('Invalid --date. Use YYYY-MM-DD.')
        return timezone.localdate() - timedelta(days=options['days_back'])
