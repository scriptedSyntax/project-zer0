# admin.py
from django.contrib import admin
from .models import UserProfile, BotSettings, BotStatus

# Registering the models for Django Admin Panel

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'deriv_token')

@admin.register(BotSettings)
class BotSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'stake', 'martingale', 'take_profit', 'stop_loss', 'prediction', 'ticks')

@admin.register(BotStatus)
class BotStatusAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_running', 'last_run_time')
