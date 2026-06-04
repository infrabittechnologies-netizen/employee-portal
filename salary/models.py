from django.db import models
from django.conf import settings
from django.utils import timezone


class SalaryComponent(models.Model):
    COMPONENT_TYPE = [
        ('allowance', 'Allowance'),
        ('deduction', 'Deduction'),
    ]
    name = models.CharField(max_length=100)
    component_type = models.CharField(max_length=20, choices=COMPONENT_TYPE)
    is_percentage = models.BooleanField(default=False)
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} ({self.component_type})"


class Payslip(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('paid', 'Paid'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payslips')
    month = models.IntegerField()
    year = models.IntegerField()
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_allowances = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    working_days = models.IntegerField(default=26)
    present_days = models.IntegerField(default=0)
    absent_days = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    generated_on = models.DateTimeField(default=timezone.now)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_payslips')
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('employee', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.employee} - {self.month}/{self.year}"

    def calculate_net(self):
        self.net_salary = self.basic_salary + self.total_allowances - self.total_deductions
        return self.net_salary


class SalaryDeduction(models.Model):
    REASON_CHOICES = [
        ('absent', 'Absent'),
        ('unpaid_leave', 'Unpaid Leave'),
        ('late', 'Late Arrival'),
        ('loan', 'Loan Repayment'),
        ('tax', 'Tax'),
        ('other', 'Other'),
    ]

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='deductions')
    payslip = models.ForeignKey(Payslip, on_delete=models.SET_NULL, null=True, blank=True, related_name='deduction_items')
    reason = models.CharField(max_length=30, choices=REASON_CHOICES, default='other')
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.now)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='applied_deductions')
    related_leave = models.ForeignKey('leaves.LeaveApplication', on_delete=models.SET_NULL, null=True, blank=True)
    month = models.IntegerField()
    year = models.IntegerField()

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.employee} - {self.reason} - {self.amount}"


class SalaryBonus(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bonuses')
    payslip = models.ForeignKey(Payslip, on_delete=models.SET_NULL, null=True, blank=True, related_name='bonus_items')
    title = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.now)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='applied_bonuses')
    month = models.IntegerField()
    year = models.IntegerField()

    def __str__(self):
        return f"{self.employee} - {self.title} - {self.amount}"
