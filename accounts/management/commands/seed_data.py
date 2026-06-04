from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import CustomUser, Department
from leaves.models import LeaveType, LeaveBalance
from holidays.models import Holiday, Announcement
from attendance.models import Attendance
from salary.models import Payslip, SalaryDeduction
from performance.models import PerformanceReview, KPI
import datetime
import random


class Command(BaseCommand):
    help = 'Seed database with sample data for demonstration'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding data...')

        # Departments
        depts = {}
        for name in ['Engineering', 'HR & Admin', 'Finance', 'Marketing', 'Operations']:
            d, _ = Department.objects.get_or_create(name=name)
            depts[name] = d
        self.stdout.write('  Departments created')

        # Leave Types — company policy: only admin-approved Paid Leave
        # Remove legacy leave types that no longer apply
        LeaveType.objects.exclude(name='Paid Leave').filter(
            applications__isnull=True
        ).delete()
        paid_leave, _ = LeaveType.objects.get_or_create(
            name='Paid Leave',
            defaults={'max_days_per_year': 365, 'is_paid': True, 'color': '#4361ee',
                      'description': 'Admin-approved paid leave. No fixed quota.'},
        )
        leave_types = {'Paid Leave': paid_leave}
        self.stdout.write('  Leave type: Paid Leave (admin-approved, no quota)')

        # Holidays
        year = timezone.now().year
        holidays_data = [
            ('New Year\'s Day', datetime.date(year, 1, 1), False),
            ('Independence Day', datetime.date(year, 8, 14), False),
            ('Eid al-Fitr', datetime.date(year, 4, 10), False),
            ('Eid al-Adha', datetime.date(year, 6, 17), False),
            ('Christmas', datetime.date(year, 12, 25), True),
            ('Labour Day', datetime.date(year, 5, 1), False),
        ]
        for name, date, optional in holidays_data:
            Holiday.objects.get_or_create(date=date, defaults={'name': name, 'is_optional': optional})
        self.stdout.write('  Holidays created')

        # Admin User
        admin, created = CustomUser.objects.get_or_create(
            username='admin',
            defaults={
                'first_name': 'System',
                'last_name': 'Admin',
                'email': 'admin@company.com',
                'role': 'admin',
                'employee_id': 'ADMIN001',
                'designation': 'System Administrator',
                'department': depts['HR & Admin'],
                'is_staff': True,
                'is_superuser': True,
                'basic_salary': 150000,
            }
        )
        if created:
            admin.set_password('admin123')
            admin.save()
        self.stdout.write('  Admin user: admin / admin123')

        # Sample Employees
        employees_data = [
            ('ahmed', 'Ahmed', 'Khan', 'ahmed@company.com', 'EMP001', 'Software Engineer', 'Engineering', 85000),
            ('sara', 'Sara', 'Ali', 'sara@company.com', 'EMP002', 'HR Manager', 'HR & Admin', 95000),
            ('bilal', 'Bilal', 'Hassan', 'bilal@company.com', 'EMP003', 'Finance Analyst', 'Finance', 80000),
            ('ayesha', 'Ayesha', 'Malik', 'ayesha@company.com', 'EMP004', 'Marketing Lead', 'Marketing', 75000),
            ('usman', 'Usman', 'Sheikh', 'usman@company.com', 'EMP005', 'Senior Developer', 'Engineering', 110000),
        ]

        created_employees = []
        today = timezone.now().date()
        for username, fname, lname, email, emp_id, designation, dept, salary in employees_data:
            emp, created = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': fname, 'last_name': lname,
                    'email': email, 'employee_id': emp_id,
                    'designation': designation,
                    'department': depts[dept],
                    'role': 'employee',
                    'joining_date': datetime.date(2023, random.randint(1, 12), random.randint(1, 28)),
                    'phone': f'+92 300 {random.randint(1000000, 9999999)}',
                    'basic_salary': salary,
                    'date_of_birth': datetime.date(1990 + random.randint(0, 8), random.randint(1, 12), random.randint(1, 28)),
                    'manager': admin,
                }
            )
            if created:
                emp.set_password('emp123')
                emp.save()
            created_employees.append(emp)

        # Manager
        mgr, created = CustomUser.objects.get_or_create(
            username='manager1',
            defaults={
                'first_name': 'Kamran', 'last_name': 'Raza',
                'email': 'kamran@company.com', 'employee_id': 'MGR001',
                'designation': 'Engineering Manager',
                'department': depts['Engineering'],
                'role': 'manager',
                'joining_date': datetime.date(2022, 3, 15),
                'basic_salary': 120000,
                'manager': admin,
            }
        )
        if created:
            mgr.set_password('mgr123')
            mgr.save()

        self.stdout.write(f'  Employees: {[e.username for e in created_employees]}')

        # No leave balance seeding — policy has no quota.
        # Existing LeaveBalance rows are left as-is to avoid data loss.

        # Attendance for current month — PKT shift times (2 PM check-in / 11 PM check-out)
        import pytz
        PKT = pytz.timezone('Asia/Karachi')
        month_start = today.replace(day=1)
        statuses = ['present', 'present', 'present', 'present', 'late', 'absent']
        for emp in created_employees:
            cur = month_start
            while cur < today:
                wd = cur.weekday()
                if wd not in (5, 6):   # skip Saturday & Sunday
                    status = random.choice(statuses)
                    if status != 'absent':
                        # On-time: Mon-Thu 14:00, Fri 15:00 | Late: +30-90 min
                        shift_h = 15 if wd == 4 else 14
                        if status == 'late':
                            late_min = random.randint(30, 90)
                            ci_h, ci_m = divmod(shift_h * 60 + late_min, 60)
                        else:
                            ci_h, ci_m = shift_h, random.randint(0, 5)
                        ci_naive = datetime.datetime(cur.year, cur.month, cur.day, ci_h, ci_m)
                        co_naive = datetime.datetime(cur.year, cur.month, cur.day, 23, random.randint(0, 10))
                        check_in  = PKT.localize(ci_naive)
                        check_out = PKT.localize(co_naive)
                        # Net work hours (deduct 95-min breaks if full shift)
                        from attendance.schedule import net_work_hours as calc_net
                        wh = calc_net(check_in, check_out)
                        Attendance.objects.get_or_create(
                            employee=emp, date=cur,
                            defaults={
                                'check_in': check_in,
                                'check_out': check_out,
                                'status': status,
                                'is_late': status == 'late',
                                'ip_address': f'192.168.1.{random.randint(100, 200)}',
                                'work_hours': wh,
                            }
                        )
                    else:
                        Attendance.objects.get_or_create(
                            employee=emp, date=cur,
                            defaults={'status': 'absent', 'work_hours': 0}
                        )
                cur += datetime.timedelta(days=1)
        self.stdout.write('  Attendance records created (PKT shift: 2 PM–11 PM)')

        # Sample Payslips
        for emp in created_employees:
            payslip, _ = Payslip.objects.get_or_create(
                employee=emp, month=today.month, year=today.year,
                defaults={
                    'basic_salary': emp.basic_salary,
                    'total_allowances': emp.basic_salary * 0.2,
                    'total_deductions': emp.basic_salary * 0.05,
                    'net_salary': emp.basic_salary * 1.15,
                    'working_days': 26,
                    'present_days': random.randint(20, 26),
                    'absent_days': random.randint(0, 3),
                    'status': 'processed',
                }
            )
        self.stdout.write('  Payslips created')

        # Sample Performance Reviews
        for emp in created_employees[:3]:
            PerformanceReview.objects.get_or_create(
                employee=emp,
                period_start=datetime.date(year, 1, 1),
                defaults={
                    'reviewed_by': admin,
                    'review_period': 'quarterly',
                    'period_end': datetime.date(year, 3, 31),
                    'rating': random.randint(3, 5),
                    'attendance_score': random.randint(14, 20),
                    'productivity_score': random.randint(14, 20),
                    'quality_score': random.randint(14, 20),
                    'teamwork_score': random.randint(14, 20),
                    'communication_score': random.randint(14, 20),
                    'comments': 'Good performance this quarter. Keep it up!',
                    'goals_next_period': 'Complete the product launch successfully.',
                }
            )
        self.stdout.write('  Performance reviews created')

        # Announcements
        Announcement.objects.get_or_create(
            title='Welcome to Employee Portal',
            defaults={
                'content': 'We are excited to launch our new Employee Management Portal! You can now track attendance, apply for leaves, and view your salary details all in one place.',
                'posted_by': admin,
                'target': 'all',
                'is_active': True,
            }
        )
        Announcement.objects.get_or_create(
            title='Q2 Performance Reviews',
            defaults={
                'content': 'Q2 performance reviews will begin next week. Please ensure all KPIs are updated before Friday.',
                'posted_by': admin,
                'target': 'all',
                'is_active': True,
            }
        )
        self.stdout.write('  Announcements created')

        self.stdout.write(self.style.SUCCESS('\n✅ Sample data seeded successfully!\n'))
        self.stdout.write('Login Credentials:')
        self.stdout.write('  Admin:   admin / admin123       -> /dashboard/admin/')
        self.stdout.write('  Manager: manager1 / mgr123')
        self.stdout.write('  Employee: ahmed / emp123  (or sara, bilal, ayesha, usman)')
        self.stdout.write('\nRun: python manage.py runserver\n')
