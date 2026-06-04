from django import forms
from django.contrib.auth import get_user_model
from .models import SalaryDeduction, SalaryBonus, Payslip

User = get_user_model()

MONTH_CHOICES = [(i, i) for i in range(1, 13)]
YEAR_CHOICES = [(y, y) for y in range(2020, 2031)]


class DeductionForm(forms.ModelForm):
    employee = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('first_name', 'last_name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    reason = forms.ChoiceField(
        choices=SalaryDeduction.REASON_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    month = forms.IntegerField(
        min_value=1,
        max_value=12,
        widget=forms.Select(choices=MONTH_CHOICES, attrs={'class': 'form-select'}),
    )
    year = forms.IntegerField(
        min_value=2020,
        max_value=2030,
        widget=forms.Select(choices=YEAR_CHOICES, attrs={'class': 'form-select'}),
    )

    class Meta:
        model = SalaryDeduction
        fields = ['employee', 'reason', 'description', 'amount', 'month', 'year']


class BonusForm(forms.ModelForm):
    employee = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('first_name', 'last_name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    title = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    month = forms.IntegerField(
        min_value=1,
        max_value=12,
        widget=forms.Select(choices=MONTH_CHOICES, attrs={'class': 'form-select'}),
    )
    year = forms.IntegerField(
        min_value=2020,
        max_value=2030,
        widget=forms.Select(choices=YEAR_CHOICES, attrs={'class': 'form-select'}),
    )

    class Meta:
        model = SalaryBonus
        fields = ['employee', 'title', 'amount', 'month', 'year']


class GeneratePayslipForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('first_name', 'last_name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    month = forms.IntegerField(
        min_value=1,
        max_value=12,
        widget=forms.Select(choices=MONTH_CHOICES, attrs={'class': 'form-select'}),
    )
    year = forms.IntegerField(
        min_value=2020,
        max_value=2030,
        widget=forms.Select(choices=YEAR_CHOICES, attrs={'class': 'form-select'}),
    )
