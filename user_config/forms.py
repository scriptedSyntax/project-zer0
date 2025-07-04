# user_config/forms.py

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
            'stake': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'martingale': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '1.0'}),
            'take_profit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'stop_loss': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'do_martingale_after': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'ticks': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'tick_result_delay': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'market': forms.Select(attrs={'class': 'form-control', 'id': 'market-select'}),
            'prediction_value': forms.NumberInput(attrs={
                'class': 'form-control', 
                'id': 'prediction-value',
                'min': '0', 
                'max': '9',
                'step': '1'
            }),
            'symbol': forms.Select(attrs={'class': 'form-control'}),
            # Keep prediction field for backward compatibility
            'prediction': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Make prediction_value optional for Even/Odd markets
        self.fields['prediction_value'].required = False
        
        # Add help text
        self.fields['prediction_value'].help_text = "Enter number 0-9 (only required for Over/Under markets)"
        self.fields['market'].help_text = "Select your prediction market type"

    def clean(self):
        cleaned_data = super().clean()
        market = cleaned_data.get('market')
        prediction_value = cleaned_data.get('prediction_value')
        
        # Validate prediction_value is required for Over/Under markets
        if market in ['OVER', 'UNDER']:
            if prediction_value is None:
                raise forms.ValidationError(
                    f"Prediction value is required when market is {market}"
                )
            if prediction_value < 0 or prediction_value > 9:
                raise forms.ValidationError(
                    "Prediction value must be between 0 and 9"
                )
        
        # For Even/Odd markets, prediction_value should be None
        elif market in ['EVEN', 'ODD']:
            cleaned_data['prediction_value'] = None
        
        return cleaned_data
