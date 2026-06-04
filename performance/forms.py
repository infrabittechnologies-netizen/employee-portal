from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import KPI, PerformanceReview

User = get_user_model()

SCORE_MIN = 0
SCORE_MAX = 20


class PerformanceReviewForm(forms.ModelForm):
    employee = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('first_name', 'last_name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    review_period = forms.ChoiceField(
        choices=PerformanceReview.PERIOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    period_start = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    period_end = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    rating = forms.ChoiceField(
        choices=PerformanceReview.RATING_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    attendance_score = forms.IntegerField(
        min_value=SCORE_MIN,
        max_value=SCORE_MAX,
        help_text='Score out of 20',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': SCORE_MIN, 'max': SCORE_MAX}),
    )
    productivity_score = forms.IntegerField(
        min_value=SCORE_MIN,
        max_value=SCORE_MAX,
        help_text='Score out of 20',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': SCORE_MIN, 'max': SCORE_MAX}),
    )
    quality_score = forms.IntegerField(
        min_value=SCORE_MIN,
        max_value=SCORE_MAX,
        help_text='Score out of 20',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': SCORE_MIN, 'max': SCORE_MAX}),
    )
    teamwork_score = forms.IntegerField(
        min_value=SCORE_MIN,
        max_value=SCORE_MAX,
        help_text='Score out of 20',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': SCORE_MIN, 'max': SCORE_MAX}),
    )
    communication_score = forms.IntegerField(
        min_value=SCORE_MIN,
        max_value=SCORE_MAX,
        help_text='Score out of 20',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': SCORE_MIN, 'max': SCORE_MAX}),
    )
    comments = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    self_evaluation = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    goals_achieved = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    goals_next_period = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    class Meta:
        model = PerformanceReview
        fields = [
            'employee',
            'review_period',
            'period_start',
            'period_end',
            'rating',
            'attendance_score',
            'productivity_score',
            'quality_score',
            'teamwork_score',
            'communication_score',
            'comments',
            'self_evaluation',
            'goals_achieved',
            'goals_next_period',
        ]

    def clean(self):
        cleaned = super().clean()
        period_start = cleaned.get('period_start')
        period_end = cleaned.get('period_end')
        if period_start and period_end and period_end < period_start:
            raise ValidationError('Period end date must be on or after the start date.')
        for field in (
            'attendance_score',
            'productivity_score',
            'quality_score',
            'teamwork_score',
            'communication_score',
        ):
            value = cleaned.get(field)
            if value is not None and not (SCORE_MIN <= value <= SCORE_MAX):
                self.add_error(field, f'Score must be between {SCORE_MIN} and {SCORE_MAX}.')
        return cleaned


class KPIForm(forms.ModelForm):
    employee = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('first_name', 'last_name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    target = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    achieved = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    status = forms.ChoiceField(
        choices=KPI.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    due_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    class Meta:
        model = KPI
        fields = ['employee', 'title', 'description', 'target', 'achieved', 'status', 'due_date']


class KPIUpdateForm(forms.ModelForm):
    """Restricted form that only allows updating achieved value and status."""
    achieved = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    status = forms.ChoiceField(
        choices=KPI.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = KPI
        fields = ['achieved', 'status']
