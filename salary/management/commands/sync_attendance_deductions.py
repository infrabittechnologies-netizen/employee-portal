"""
Apply the attendance-based salary-deduction rule to existing attendance.

For every Attendance record (optionally filtered to a month/year or date
range) this recomputes the auto deduction and stores a single aggregated
``SalaryDeduction`` row (``source='attendance'``) for that employee/day —
exactly what happens automatically on check-out and in the daily finaliser.

It is **idempotent**: any prior ``source='attendance'`` row for a day is
replaced, and ``source='manual'`` admin deductions are never touched. So it is
safe to run repeatedly. Use it to "switch on" deductions across attendance that
predates the feature, or to recompute after a rule change.

Usage:
    python manage.py sync_attendance_deductions                 # all attendance
    python manage.py sync_attendance_deductions --month 6 --year 2026
    python manage.py sync_attendance_deductions --from 2026-06-01 --to 2026-06-30
    python manage.py sync_attendance_deductions --dry-run        # report only
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from attendance.models import Attendance
from salary.deductions import sync_attendance_deduction


class Command(BaseCommand):
    help = (
        "Recompute and persist attendance-based salary deductions for existing "
        "attendance records (idempotent; never touches manual deductions)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--month', type=int, default=None,
                            help='Only this month (1-12). Use with --year.')
        parser.add_argument('--year', type=int, default=None,
                            help='Only this year (e.g. 2026).')
        parser.add_argument('--from', dest='date_from', type=str, default=None,
                            help='Start date YYYY-MM-DD (inclusive).')
        parser.add_argument('--to', dest='date_to', type=str, default=None,
                            help='End date YYYY-MM-DD (inclusive).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would change without writing.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        qs = Attendance.objects.select_related('employee').prefetch_related(
            'break_restarts'
        ).order_by('date')

        if options['month']:
            qs = qs.filter(date__month=options['month'])
        if options['year']:
            qs = qs.filter(date__year=options['year'])
        if options['date_from']:
            qs = qs.filter(date__gte=self._parse('--from', options['date_from']))
        if options['date_to']:
            qs = qs.filter(date__lte=self._parse('--to', options['date_to']))

        total = qs.count()
        self.stdout.write(f'Processing {total} attendance record(s)…')

        with_deduction = 0
        deducted_amount = 0

        with transaction.atomic():
            for att in qs.iterator(chunk_size=200):
                result = sync_attendance_deduction(att)
                if result['amount'] > 0:
                    with_deduction += 1
                    deducted_amount += result['amount']
                    label = att.employee.get_full_name() or att.employee.username
                    self.stdout.write(
                        f'  {att.date}  {label:22}  Rs {result["amount"]:>9}'
                        f'  {result["description"]}'
                    )
            if dry_run:
                transaction.set_rollback(True)

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Done. {with_deduction} of {total} day(s) carry a deduction; '
            f'total Rs {deducted_amount}.'
        ))

    def _parse(self, flag, value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            raise CommandError(f'Invalid {flag}. Use YYYY-MM-DD.')
