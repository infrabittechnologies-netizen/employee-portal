"""
seed_demo — populate a LOCAL/sample database with ~2 months of realistic
employee data so the admin panel can be explored (attendance, leaves,
payslips, deductions, bonuses, performance reviews, KPIs).

SAFETY
------
This command is for a *sample* portal only. It refuses to run when a
DATABASE_URL is configured (i.e. against the production Postgres) unless
you explicitly pass --force. Run it locally where the app uses SQLite.

Usage
-----
    python manage.py seed_demo            # seed ~2 months of demo data
    python manage.py seed_demo --months 1 # only last 1 month
    python manage.py seed_demo --fresh    # wipe previous demo data first
"""

import os
import random
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from accounts.models import CustomUser, Department
from attendance.models import Attendance
from leaves.models import LeaveType, LeaveApplication
from salary.models import Payslip, SalaryDeduction, SalaryBonus
from performance.models import PerformanceReview, KPI
from attendance.schedule import SHIFT_START, SHIFT_END, is_weekend


DEMO_PASSWORD = 'demo12345'

# Sample people: (first, last, designation, department, role, salary)
DEMO_PEOPLE = [
    ('Demo', 'Admin',   'Operations Head',   'Management',  'admin',    220000),
    ('Ali',  'Raza',    'Team Lead',         'Development', 'manager',  180000),
    ('Sara', 'Khan',    'Frontend Engineer', 'Development', 'employee', 120000),
    ('Bilal','Ahmed',   'Backend Engineer',  'Development', 'employee', 130000),
    ('Hina', 'Malik',   'UI/UX Designer',    'Design',      'employee', 100000),
    ('Usman','Tariq',   'Sales Executive',   'Sales',       'employee',  90000),
]

KPI_BANK = [
    ('Close 10 support tickets/week', '10 tickets', 'achieved'),
    ('Ship dashboard redesign',        '1 release',  'on_track'),
    ('Reduce page load to <2s',        '2 seconds',  'in_progress'),
    ('Onboard 5 new clients',          '5 clients',  'missed'),
    ('Write unit tests (80% cover)',   '80%',        'on_track'),
]

REVIEW_COMMENTS = [
    'Consistently meets deadlines and collaborates well with the team.',
    'Strong technical output this period; communication can improve slightly.',
    'Excellent ownership of tasks and proactive problem solving.',
    'Good progress overall, attendance was very regular.',
]


class Command(BaseCommand):
    help = 'Seed the local/sample database with ~2 months of demo employee data.'

    def add_arguments(self, parser):
        parser.add_argument('--months', type=int, default=2,
                            help='How many months of history to generate (default 2).')
        parser.add_argument('--fresh', action='store_true',
                            help='Delete previously seeded demo users first.')
        parser.add_argument('--force', action='store_true',
                            help='Run even if DATABASE_URL is set (DANGEROUS).')

    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        if os.environ.get('DATABASE_URL') and not opts['force']:
            self.stderr.write(self.style.ERROR(
                'DATABASE_URL is set — this looks like production.\n'
                'seed_demo is for a LOCAL sample portal only. Aborting.\n'
                'Run it locally (SQLite) or pass --force if you really mean it.'
            ))
            return

        months = max(1, opts['months'])
        today = timezone.localdate()
        start_date = today - datetime.timedelta(days=months * 31)

        with transaction.atomic():
            if opts['fresh']:
                self._wipe_demo()

            depts = self._ensure_departments()
            people = self._ensure_people(depts)
            leave_types = self._ensure_leave_types()

            employees = [u for u in people if u.role in ('employee', 'manager')]
            admin = next((u for u in people if u.role == 'admin'), None)

            total_att = 0
            for emp in employees:
                total_att += self._seed_attendance(emp, start_date, today)
                self._seed_leaves(emp, leave_types, admin, start_date, today)
                self._seed_payslips(emp, admin, months, today)
                self._seed_performance(emp, admin, months, today)
                self._seed_kpis(emp, today)

        self.stdout.write(self.style.SUCCESS(
            f'\nDemo data seeded: {len(employees)} employees, '
            f'{total_att} attendance records, {months} month(s) of payroll/reviews.'
        ))
        self.stdout.write(self.style.WARNING(
            f'\nLogin credentials (all demo users): password = "{DEMO_PASSWORD}"'
        ))
        for u in people:
            self.stdout.write(f'  • {u.username:14s} ({u.role})')
        self.stdout.write(self.style.SUCCESS(
            '\nStart the server with:  python manage.py runserver\n'
            'Then open http://127.0.0.1:8000/ and log in as "demo_admin".'
        ))

    # ------------------------------------------------------------------ #
    def _wipe_demo(self):
        qs = CustomUser.objects.filter(username__startswith='demo_') | \
             CustomUser.objects.filter(username__in=[
                 'ali_raza', 'sara_khan', 'bilal_ahmed', 'hina_malik', 'usman_tariq'])
        count = qs.count()
        qs.delete()  # cascades to all owned records
        self.stdout.write(self.style.WARNING(f'Wiped {count} previous demo user(s).'))

    def _ensure_departments(self):
        depts = {}
        for name in ['Management', 'Development', 'Design', 'Sales']:
            d, _ = Department.objects.get_or_create(name=name)
            depts[name] = d
        return depts

    def _ensure_leave_types(self):
        defaults = [
            ('Casual Leave', 10, True,  '#0ea5e9'),
            ('Sick Leave',   8,  True,  '#ef4444'),
            ('Annual Leave', 14, True,  '#10b981'),
            ('Unpaid Leave', 0,  False, '#94a3b8'),
        ]
        out = []
        for name, maxd, paid, color in defaults:
            lt, _ = LeaveType.objects.get_or_create(
                name=name,
                defaults={'max_days_per_year': maxd, 'is_paid': paid, 'color': color},
            )
            out.append(lt)
        return out

    def _free_employee_id(self, seq):
        """Return a demo employee id (DMO###) that is not already taken."""
        while True:
            candidate = f'DMO{seq:03d}'
            if not CustomUser.objects.filter(employee_id=candidate).exists():
                return candidate
            seq += 1

    def _ensure_people(self, depts):
        created = []
        emp_seq = 1
        manager_obj = None
        for first, last, desig, dept, role, salary in DEMO_PEOPLE:
            if role == 'admin':
                username = 'demo_admin'
            else:
                username = f'{first}_{last}'.lower()
            user, is_new = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': f'{username}@demo.infrabit.tech',
                    'role': role,
                    'designation': desig,
                    'department': depts.get(dept),
                    'employee_id': self._free_employee_id(emp_seq),
                    'basic_salary': Decimal(salary),
                    'joining_date': timezone.localdate() - datetime.timedelta(days=400),
                    'is_active': True,
                    'is_staff': role == 'admin',
                    'is_superuser': role == 'admin',
                },
            )
            if is_new:
                user.set_password(DEMO_PASSWORD)
                user.save()
            emp_seq += 1
            if role == 'manager':
                manager_obj = user
            created.append(user)

        # Wire reporting lines: employees -> the demo manager
        if manager_obj:
            for u in created:
                if u.role == 'employee' and u.manager_id is None:
                    u.manager = manager_obj
                    u.save(update_fields=['manager'])
        return created

    # ------------------------------------------------------------------ #
    def _aware(self, d, t):
        return timezone.make_aware(datetime.datetime.combine(d, t))

    def _seed_attendance(self, emp, start_date, today):
        # Clear any existing attendance in range to stay idempotent
        Attendance.objects.filter(employee=emp, date__gte=start_date, date__lte=today).delete()

        count = 0
        day = start_date
        while day <= today:
            if is_weekend(day):
                day += datetime.timedelta(days=1)
                continue

            roll = random.random()
            shift_start = SHIFT_START.get(day.weekday())

            if roll < 0.06:
                # Absent
                Attendance.objects.create(employee=emp, date=day, status='absent')
            elif roll < 0.10:
                # On leave (paid)
                Attendance.objects.create(employee=emp, date=day, status='leave')
            else:
                # Present (sometimes late)
                late = roll > 0.80
                minute_offset = random.randint(8, 35) if late else random.randint(-3, 2)
                ci_time = (datetime.datetime.combine(day, shift_start)
                           + datetime.timedelta(minutes=minute_offset)).time()
                # check-out near shift end, small variation
                co_offset = random.randint(-15, 20)
                co_time = (datetime.datetime.combine(day, SHIFT_END)
                           + datetime.timedelta(minutes=co_offset)).time()
                att = Attendance(
                    employee=emp,
                    date=day,
                    check_in=self._aware(day, ci_time),
                    check_out=self._aware(day, co_time),
                    location='Office — Infrabit HQ',
                    ip_address='192.168.1.{}'.format(random.randint(10, 200)),
                )
                att.save()  # auto-computes is_late / status / work_hours
            count += 1
            day += datetime.timedelta(days=1)
        return count

    def _seed_leaves(self, emp, leave_types, admin, start_date, today):
        LeaveApplication.objects.filter(employee=emp).delete()
        statuses = ['approved', 'approved', 'pending', 'rejected']
        for i in range(random.randint(1, 3)):
            lt = random.choice(leave_types)
            frm = start_date + datetime.timedelta(days=random.randint(5, (today - start_date).days - 3))
            to = frm + datetime.timedelta(days=random.randint(0, 2))
            status = random.choice(statuses)
            la = LeaveApplication(
                employee=emp,
                leave_type=lt,
                from_date=frm,
                to_date=to,
                reason=random.choice([
                    'Family function', 'Medical appointment',
                    'Personal work', 'Out of city', 'Not feeling well',
                ]),
                status=status,
                applied_on=self._aware(frm - datetime.timedelta(days=3),
                                       datetime.time(12, 0)),
            )
            if status in ('approved', 'rejected'):
                la.reviewed_by = admin
                la.reviewed_on = timezone.now()
                la.review_comment = ('Approved — enjoy your time off.'
                                     if status == 'approved'
                                     else 'Rejected due to workload this week.')
            la.save()

    def _seed_payslips(self, emp, admin, months, today):
        Payslip.objects.filter(employee=emp).delete()
        SalaryDeduction.objects.filter(employee=emp).delete()
        SalaryBonus.objects.filter(employee=emp).delete()

        for back in range(months):
            ref = (today.replace(day=1) - datetime.timedelta(days=back * 30)).replace(day=1)
            month, year = ref.month, ref.year

            month_att = Attendance.objects.filter(
                employee=emp, date__month=month, date__year=year)
            present = month_att.filter(status__in=['present', 'late']).count()
            absent = month_att.filter(status='absent').count()
            late = month_att.filter(status='late').count()

            basic = emp.basic_salary or Decimal('0')
            allowances = (basic * Decimal('0.15')).quantize(Decimal('1'))

            # Deductions: per-absent + per-late penalties
            per_day = (basic / Decimal('26')).quantize(Decimal('1'))
            absent_ded = (per_day * absent).quantize(Decimal('1'))
            late_ded = (Decimal('500') * late).quantize(Decimal('1'))
            total_ded = absent_ded + late_ded

            payslip = Payslip.objects.create(
                employee=emp, month=month, year=year,
                basic_salary=basic, total_allowances=allowances,
                total_deductions=total_ded,
                net_salary=basic + allowances - total_ded,
                working_days=26, present_days=present, absent_days=absent,
                status=random.choice(['processed', 'paid']),
                processed_by=admin,
            )
            if absent_ded > 0:
                SalaryDeduction.objects.create(
                    employee=emp, payslip=payslip, reason='absent',
                    description=f'{absent} day(s) absent', amount=absent_ded,
                    date=ref, applied_by=admin, month=month, year=year)
            if late_ded > 0:
                SalaryDeduction.objects.create(
                    employee=emp, payslip=payslip, reason='late',
                    description=f'{late} late arrival(s)', amount=late_ded,
                    date=ref, applied_by=admin, month=month, year=year)

            # Occasional performance bonus
            if random.random() < 0.4:
                SalaryBonus.objects.create(
                    employee=emp, payslip=payslip, title='Performance Bonus',
                    amount=Decimal('5000'), date=ref, applied_by=admin,
                    month=month, year=year)

    def _seed_performance(self, emp, admin, months, today):
        PerformanceReview.objects.filter(employee=emp).delete()
        for back in range(months):
            ref = (today.replace(day=1) - datetime.timedelta(days=back * 30)).replace(day=1)
            nxt = (ref + datetime.timedelta(days=32)).replace(day=1)
            period_end = nxt - datetime.timedelta(days=1)
            scores = [random.randint(12, 20) for _ in range(5)]
            PerformanceReview.objects.create(
                employee=emp, reviewed_by=admin, review_period='monthly',
                period_start=ref, period_end=period_end,
                rating=random.randint(3, 5),
                attendance_score=scores[0], productivity_score=scores[1],
                quality_score=scores[2], teamwork_score=scores[3],
                communication_score=scores[4],
                comments=random.choice(REVIEW_COMMENTS),
                goals_achieved='Completed assigned sprint tasks on time.',
                goals_next_period='Improve code review turnaround.',
                created_at=self._aware(period_end, datetime.time(17, 0)),
            )

    def _seed_kpis(self, emp, today):
        KPI.objects.filter(employee=emp).delete()
        for title, target, status in random.sample(KPI_BANK, k=3):
            KPI.objects.create(
                employee=emp, title=title, target=target,
                achieved=target if status == 'achieved' else '',
                status=status,
                due_date=today + datetime.timedelta(days=random.randint(-10, 30)),
            )
