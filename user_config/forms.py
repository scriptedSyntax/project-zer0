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
            field: forms.NumberInput(attrs={'class': 'form-control'})
            for field in [
                'stake', 'martingale', 'take_profit', 'stop_loss',
                'do_martingale_after', 'prediction', 'ticks', 'loss_counter'
            ]
        }
        widgets['entry_point_symbol'] = forms.TextInput(attrs={'class': 'form-control'})
