from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordChangeForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Submit, Field, Div, HTML

from .models import CustomUser, Department


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your username',
            'autofocus': True,
        }),
        label='Username',
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
        }),
        label='Password',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('username', css_class='mb-3'),
            Field('password', css_class='mb-3'),
            Submit('submit', 'Sign In', css_class='btn btn-primary w-100'),
        )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            user = authenticate(username=username, password=password)
            if user is None:
                raise forms.ValidationError('Invalid username or password.')
            if not user.is_active:
                raise forms.ValidationError('This account has been deactivated.')
            cleaned_data['user'] = user
        return cleaned_data


# ---------------------------------------------------------------------------
# Employee Registration (admin creates employees)
# ---------------------------------------------------------------------------

class EmployeeRegistrationForm(forms.ModelForm):
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'}),
    )

    class Meta:
        model = CustomUser
        fields = [
            'employee_id',
            'first_name',
            'last_name',
            'username',
            'email',
            'phone',
            'designation',
            'department',
            'role',
            'joining_date',
            'basic_salary',
            'date_of_birth',
            'address',
            'emergency_contact',
            'manager',
        ]
        widgets = {
            'employee_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. EMP001'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'designation': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Job title / designation'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'basic_salary': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Full address'}),
            'emergency_contact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Emergency contact number'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show users who are managers or admins as selectable managers
        self.fields['manager'].queryset = CustomUser.objects.filter(
            role__in=['admin', 'manager'], is_active=True
        )
        self.fields['manager'].required = False
        self.fields['department'].required = False

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            HTML('<h5 class="mb-3 text-muted">Personal Information</h5>'),
            Row(
                Column('first_name', css_class='col-md-6 mb-3'),
                Column('last_name', css_class='col-md-6 mb-3'),
            ),
            Row(
                Column('date_of_birth', css_class='col-md-6 mb-3'),
                Column('phone', css_class='col-md-6 mb-3'),
            ),
            'address',
            HTML('<hr><h5 class="mb-3 mt-3 text-muted">Account Credentials</h5>'),
            Row(
                Column('username', css_class='col-md-6 mb-3'),
                Column('email', css_class='col-md-6 mb-3'),
            ),
            Row(
                Column('password1', css_class='col-md-6 mb-3'),
                Column('password2', css_class='col-md-6 mb-3'),
            ),
            HTML('<hr><h5 class="mb-3 mt-3 text-muted">Employment Details</h5>'),
            Row(
                Column('employee_id', css_class='col-md-4 mb-3'),
                Column('designation', css_class='col-md-4 mb-3'),
                Column('role', css_class='col-md-4 mb-3'),
            ),
            Row(
                Column('department', css_class='col-md-6 mb-3'),
                Column('manager', css_class='col-md-6 mb-3'),
            ),
            Row(
                Column('joining_date', css_class='col-md-6 mb-3'),
                Column('basic_salary', css_class='col-md-6 mb-3'),
            ),
            'emergency_contact',
            Submit('submit', 'Create Employee', css_class='btn btn-primary mt-3'),
        )

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError('Passwords do not match.')
        return password2

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError('A user with this username already exists.')
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


# ---------------------------------------------------------------------------
# Employee Update (no passwords)
# ---------------------------------------------------------------------------

class EmployeeUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = [
            'employee_id',
            'first_name',
            'last_name',
            'username',
            'email',
            'phone',
            'designation',
            'department',
            'role',
            'joining_date',
            'basic_salary',
            'date_of_birth',
            'address',
            'emergency_contact',
            'manager',
            'is_active',
        ]
        widgets = {
            'employee_id': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'basic_salary': forms.NumberInput(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'emergency_contact': forms.TextInput(attrs={'class': 'form-control'}),
            'manager': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['manager'].queryset = CustomUser.objects.filter(
            role__in=['admin', 'manager'], is_active=True
        )
        self.fields['manager'].required = False
        self.fields['department'].required = False

        # Exclude the user being edited from the manager dropdown to avoid self-reference
        if self.instance and self.instance.pk:
            self.fields['manager'].queryset = self.fields['manager'].queryset.exclude(
                pk=self.instance.pk
            )

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            HTML('<h5 class="mb-3 text-muted">Personal Information</h5>'),
            Row(
                Column('first_name', css_class='col-md-6 mb-3'),
                Column('last_name', css_class='col-md-6 mb-3'),
            ),
            Row(
                Column('date_of_birth', css_class='col-md-6 mb-3'),
                Column('phone', css_class='col-md-6 mb-3'),
            ),
            'address',
            HTML('<hr><h5 class="mb-3 mt-3 text-muted">Account Details</h5>'),
            Row(
                Column('username', css_class='col-md-6 mb-3'),
                Column('email', css_class='col-md-6 mb-3'),
            ),
            HTML('<hr><h5 class="mb-3 mt-3 text-muted">Employment Details</h5>'),
            Row(
                Column('employee_id', css_class='col-md-4 mb-3'),
                Column('designation', css_class='col-md-4 mb-3'),
                Column('role', css_class='col-md-4 mb-3'),
            ),
            Row(
                Column('department', css_class='col-md-6 mb-3'),
                Column('manager', css_class='col-md-6 mb-3'),
            ),
            Row(
                Column('joining_date', css_class='col-md-6 mb-3'),
                Column('basic_salary', css_class='col-md-6 mb-3'),
            ),
            'emergency_contact',
            Field('is_active', css_class='mb-3'),
            Submit('submit', 'Save Changes', css_class='btn btn-primary mt-3'),
        )

    def clean_username(self):
        username = self.cleaned_data.get('username')
        qs = CustomUser.objects.filter(username=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A user with this username already exists.')
        return username


# ---------------------------------------------------------------------------
# Profile Picture
# ---------------------------------------------------------------------------

class ProfilePictureForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['profile_picture']
        widgets = {
            'profile_picture': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.attrs = {'enctype': 'multipart/form-data'}
        self.helper.layout = Layout(
            Field('profile_picture', css_class='mb-3'),
            Submit('submit', 'Update Picture', css_class='btn btn-primary'),
        )


# ---------------------------------------------------------------------------
# Change Password (wraps Django's built-in PasswordChangeForm with crispy)
# ---------------------------------------------------------------------------

class ChangePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('old_password', css_class='mb-3'),
            Field('new_password1', css_class='mb-3'),
            Field('new_password2', css_class='mb-3'),
            Submit('submit', 'Change Password', css_class='btn btn-warning'),
        )
