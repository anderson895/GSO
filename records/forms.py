from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import WasteRecord, Profile, Area

AMOUNT_CHOICES = [(str(x / 4), f"{x / 4:.2f}") for x in range(1, 41)]

class WasteForm(forms.ModelForm):
    amount = forms.ChoiceField(choices=AMOUNT_CHOICES, label='Amount')

    class Meta:
        model = WasteRecord
        fields = ['area', 'waste_type', 'amount', 'date', 'time', 'photo']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'time': forms.TimeInput(attrs={'type': 'time'}),
        }
        labels = {
            'area': 'Area / Building',
            'waste_type': 'Waste Type',
            'photo': 'Upload Photo',
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise forms.ValidationError('Invalid amount selected.')
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['area'].queryset = Area.objects.filter(
            status='Active'
        )


class EditWasteForm(forms.ModelForm):
    amount = forms.ChoiceField(choices=AMOUNT_CHOICES, label='Amount')

    class Meta:
        model = WasteRecord
        fields = ['area', 'waste_type', 'amount', 'date', 'time', 'photo']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'time': forms.TimeInput(attrs={'type': 'time'}),
        }
        labels = {
            'area': 'Area / Building',
            'waste_type': 'Waste Type',
            'photo': 'Upload Photo',
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise forms.ValidationError('Invalid amount selected.')
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount



class RegisterForm(UserCreationForm):
    ROLE_CHOICES = [
        ('Head Supervisor', 'Head Supervisor'),
        ('Supervisor', 'Supervisor'),
        ('Lead Janitor', 'Lead Janitor'),
    ]

    role = forms.ChoiceField(choices=ROLE_CHOICES)

    class Meta:
        model = User
        fields = ['username', 'role', 'password1', 'password2']
        labels = {
            'username': 'User ID',
        }

    def clean(self):
        cleaned_data = super().clean()
        employee_id = cleaned_data.get('username')
        role = cleaned_data.get('role')

        if not employee_id:
            raise forms.ValidationError('User ID is required.')

        employee_id = employee_id.strip().upper()
        cleaned_data['username'] = employee_id

        if User.objects.filter(username=employee_id).exists():
            raise forms.ValidationError('This User ID is already registered.')

        if Profile.objects.filter(employee_id=employee_id).exists():
            raise forms.ValidationError('This User ID is already registered.')

        return cleaned_data
