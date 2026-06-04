from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import LeaveApplication, LeaveBalance, LeaveType


class LeaveApplicationForm(forms.ModelForm):
    """Form used by employees to apply for leave."""

    class Meta:
        model = LeaveApplication
        fields = [
            'leave_type',
            'from_date',
            'to_date',
            'reason',
            'is_half_day',
            'document',
        ]
        widgets = {
            'leave_type': forms.Select(
                attrs={
                    'class': 'form-select',
                    'id': 'id_leave_type',
                }
            ),
            'from_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                    'id': 'id_from_date',
                }
            ),
            'to_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                    'id': 'id_to_date',
                }
            ),
            'reason': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 4,
                    'placeholder': 'Please provide a reason for your leave request…',
                }
            ),
            'is_half_day': forms.CheckboxInput(
                attrs={'class': 'form-check-input'}
            ),
            'document': forms.ClearableFileInput(
                attrs={'class': 'form-control'}
            ),
        }
        labels = {
            'leave_type': 'Leave Type',
            'from_date': 'From Date',
            'to_date': 'To Date',
            'reason': 'Reason',
            'is_half_day': 'Half Day',
            'document': 'Supporting Document (optional)',
        }
        help_texts = {
            'document': 'Upload a medical certificate or any supporting document (PDF, JPEG, PNG).',
            'is_half_day': 'Check this box if you are applying for only half a day.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only Paid Leave is available per company policy.
        paid_qs = LeaveType.objects.filter(is_paid=True).order_by('name')
        self.fields['leave_type'].queryset = paid_qs
        # Auto-select if there is exactly one option
        if paid_qs.count() == 1:
            self.fields['leave_type'].initial = paid_qs.first()
            self.fields['leave_type'].widget.attrs['style'] = 'display:none;'
            self.fields['leave_type'].label = ''   # hidden but still submitted
        self.fields['from_date'].required = True
        self.fields['to_date'].required = True
        self.fields['reason'].required = True

    def clean_from_date(self):
        from_date = self.cleaned_data.get('from_date')
        today = timezone.localdate()
        if from_date and from_date < today:
            raise ValidationError('The start date cannot be in the past.')
        return from_date

    def clean(self):
        cleaned_data = super().clean()
        from_date = cleaned_data.get('from_date')
        to_date = cleaned_data.get('to_date')
        is_half_day = cleaned_data.get('is_half_day')

        if from_date and to_date:
            if to_date < from_date:
                raise ValidationError('The end date must be on or after the start date.')

            if is_half_day and from_date != to_date:
                raise ValidationError(
                    'For a half-day leave, the from-date and to-date must be the same day.'
                )

        return cleaned_data


class LeaveReviewForm(forms.ModelForm):
    """Form used by managers/admins to approve or reject a leave application."""

    STATUS_CHOICES = [
        ('approved', 'Approve'),
        ('rejected', 'Reject'),
    ]

    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='Decision',
    )

    class Meta:
        model = LeaveApplication
        fields = ['status', 'review_comment']
        widgets = {
            'review_comment': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Optional: add a comment for the employee…',
                }
            ),
        }
        labels = {
            'review_comment': 'Review Comment',
        }

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        review_comment = cleaned_data.get('review_comment', '').strip()

        if status == 'rejected' and not review_comment:
            raise ValidationError(
                'A review comment is required when rejecting a leave application.'
            )

        return cleaned_data


class LeaveTypeForm(forms.ModelForm):
    """Form used by admins to create / update leave types."""

    class Meta:
        model = LeaveType
        fields = ['name', 'max_days_per_year', 'is_paid', 'color', 'description']
        widgets = {
            'name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. Annual Leave, Sick Leave…',
                }
            ),
            'max_days_per_year': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'min': 0,
                    'max': 365,
                }
            ),
            'is_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'color': forms.TextInput(
                attrs={
                    'class': 'form-control form-control-color',
                    'type': 'color',
                    'title': 'Choose a colour for calendar display',
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Optional description…',
                }
            ),
        }
        labels = {
            'name': 'Leave Type Name',
            'max_days_per_year': 'Maximum Days Per Year',
            'is_paid': 'Paid Leave',
            'color': 'Calendar Colour',
            'description': 'Description',
        }

    def clean_max_days_per_year(self):
        value = self.cleaned_data.get('max_days_per_year')
        if value is not None and value < 0:
            raise ValidationError('Maximum days cannot be negative.')
        return value

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise ValidationError('Leave type name cannot be blank.')
        return name
