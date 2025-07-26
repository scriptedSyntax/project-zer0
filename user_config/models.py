# user_config/models.py

from django.db import models
from django.contrib.auth.models import User

PREDICTION_CHOICES = [
    ('even', 'Even'),
    ('odd', 'Odd'),
    ('rise', 'Rise'),
    ('fall', 'Fall'),  # ✅ 
]

MARKET_CHOICES = [
    ('even_odd', 'Even/Odd'),
    ('over', 'Over'),
    ('under', 'Under'),
    ('matches', 'Matches'),
    ('differs', 'Differs'),
    ('rise_fall', 'Rise/Fall'), 
]

SYMBOL_CHOICES = [
    ('R_100', 'Volatility 100 Index'),
    ('1HZ100V', 'Volatility 100 (1s) Index'),
    ('1HZ10V', 'Volatility 10 (1s) Index'),
    ('R_10', 'Volatility 10 Index'),
    ('R_50', 'Volatility 50 Index'),
    ('1HZ25V', 'Volatility 25 (1s) Index'),
    ('1HZ75V', 'Volatility 75 (1s) Index'),
    ('R_25', 'Volatility 25 Index'),
    ('R_75', 'Volatility 75 Index'),
    ('1HZ50V', 'Volatility 50 (1s) Index'),
]

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    deriv_token = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.user.username} Profile"

class BotSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    stake = models.FloatField(default=1.0)
    martingale = models.FloatField(default=2.0)
    take_profit = models.FloatField(default=10.0)
    stop_loss = models.FloatField(default=10.0)
    do_martingale_after = models.IntegerField(default=1)

    prediction = models.CharField(max_length=10, choices=PREDICTION_CHOICES, default='even')
    ticks = models.IntegerField(default=1)
    symbol = models.CharField(max_length=20, choices=SYMBOL_CHOICES, default="R_50")
    tick_result_delay = models.IntegerField(default=1)

    market_type = models.CharField(max_length=20, choices=MARKET_CHOICES, default='even_odd')
    threshold = models.IntegerField(null=True, blank=True)  # Only used for over/under markets
    recovery_threshold = models.IntegerField(null=True, blank=True)

    stop_after_losses = models.IntegerField(default=0, help_text="Stop bot after X consecutive losses")

    def __str__(self):
        return f"{self.user.username} Bot Settings"

class BotStatus(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_running = models.BooleanField(default=False)
    last_run_time = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} Bot Running: {self.is_running}"
