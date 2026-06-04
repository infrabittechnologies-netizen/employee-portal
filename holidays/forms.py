from django import forms
from accounts.models import Department
from .models import Announcement, Holiday


class HolidayForm(forms.ModelForm):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    is_optional = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Optional Holiday',
    )

    class Meta:
        model = Holiday
        fields = ['name', 'date', 'description', 'is_optional']


class AnnouncementForm(forms.ModelForm):
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    content = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
    )
    target = forms.ChoiceField(
        choices=Announcement.TARGET_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.all().order_by('name'),
        required=False,
        empty_label='-- Select Department (optional) --',
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Required only when target is "Specific Department".',
    )

    class Meta:
        model = Announcement
        fields = ['title', 'content', 'target', 'department']

    def clean(self):
        cleaned = super().clean()
        target = cleaned.get('target')
        department = cleaned.get('department')
        if target == 'department' and not department:
            self.add_error('department', 'Please select a department for department-targeted announcements.')
        return cleaned
