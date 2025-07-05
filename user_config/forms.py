from django import forms
from .models import UserProfile, BotSettings

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['deriv_token']
        widgets = {
            'deriv_token': forms.TextInput(attrs={'class': 'form-control'}),
        }

class BotSettingsForm(forms.ModelForm):
    class Meta:
        model = BotSettings
        exclude = ['user']
        widgets = {
            'stake': forms.NumberInput(attrs={'class': 'form-control'}),
            'martingale': forms.NumberInput(attrs={'class': 'form-control'}),
            'take_profit': forms.NumberInput(attrs={'class': 'form-control'}),
            'stop_loss': forms.NumberInput(attrs={'class': 'form-control'}),
            'do_martingale_after': forms.NumberInput(attrs={'class': 'form-control'}),
            'prediction': forms.Select(attrs={'class': 'form-control'}),
            'ticks': forms.NumberInput(attrs={'class': 'form-control'}),
            'tick_result_delay': forms.NumberInput(attrs={'class': 'form-control'}),
            'threshold': forms.NumberInput(attrs={'class': 'form-control'}),
            'market_type': forms.Select(attrs={'class': 'form-control'}),
            'symbol': forms.Select(attrs={'class': 'form-control'}),
            'recovery_threshold': forms.NumberInput(attrs={'class': 'form-control'}),
        }
