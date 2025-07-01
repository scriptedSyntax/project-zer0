from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login, logout
from django.http import JsonResponse
from asgiref.sync import async_to_sync

from user_config.models import SYMBOL_CHOICES, UserProfile, BotSettings, BotStatus
from user_config.forms import UserProfileForm, BotSettingsForm
from utils.deriv_api import get_account_balance

@login_required
def dashboard_view(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    settings, _ = BotSettings.objects.get_or_create(user=user)
    status, _ = BotStatus.objects.get_or_create(user=user)

    profile_form = UserProfileForm(instance=profile)
    settings_form = BotSettingsForm(instance=settings)

    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if request.method == 'POST':
        action = request.POST.get('action', '')  # Expect "update_token" or "update_settings"

        # Update token
        if action == 'update_token':
            profile_form = UserProfileForm(request.POST, instance=profile)
            if profile_form.is_valid():
                profile_form.save()
                if is_ajax:
                    return JsonResponse({"status": "success", "message": "Token updated"})
                return redirect('dashboard')
            else:
                if is_ajax:
                    return JsonResponse({"status": "error", "message": "Invalid token data"}, status=400)
                return redirect('dashboard')

        # Update bot settings
        elif action == 'update_settings':
            settings_form = BotSettingsForm(request.POST, instance=settings)
            if settings_form.is_valid():
                updated_settings = settings_form.save(commit=False)
                # updated_settings.user = request.user  # ✅ Set the user explicitly
                updated_settings.symbol = request.POST.get('symbol', updated_settings.symbol)
                updated_settings.tick_result_delay = 1  # ✅ Set manually
                updated_settings.save()

                if is_ajax:
                    return JsonResponse({"status": "success", "message": "Settings saved"})
                return redirect('dashboard')
            else:
                print(settings_form.errors) 
                if is_ajax:
                    return JsonResponse({"status": "error", "message": "Invalid settings data"}, status=400)
                return redirect('dashboard')

    # Fetch account balance
    balance, currency = 0.0, "USD"
    try:
        if profile.deriv_token:
            balance, currency = async_to_sync(get_account_balance)(profile.deriv_token)
    except Exception as e:
        print(f"[ERROR] Balance fetch failed: {e}")

    bot_status_text = "Running" if status.is_running else "Stopped"
    bot_status_class = "status-running" if status.is_running else "status-stopped"

    return render(request, 'dashboard/dashboard.html', {
        'profile_form': profile_form,
        'settings_form': settings_form,
        'bot_status': status,
        'balance': balance,
        'currency': currency,
        'bot_status_text': bot_status_text,
        'bot_status_class': bot_status_class,
        'symbol_choices': dict(SYMBOL_CHOICES),
    })


def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.create(user=user)
            BotSettings.objects.create(user=user)
            BotStatus.objects.create(user=user)
            login(request, user)
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})

@login_required
def logout_view(request):
    logout(request)
    return redirect('login')
