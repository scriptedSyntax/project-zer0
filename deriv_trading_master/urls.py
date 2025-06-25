from django.contrib import admin
from django.urls import path, include, re_path
from django.contrib.auth import views as auth_views
from django.views.static import serve
from dashboard import views as dashboard_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),  # Dashboard app → default home

    # Auth system
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/login/'), name='logout'),
    path('register/', dashboard_views.register, name='register'),
]


# 👇 Add these lines at the END
urlpatterns += [
    re_path(r'^favicon\.png$', serve, {
        'path': 'bitcoin.png',
        'document_root': settings.BASE_DIR,
    }),
]
# This file defines the URL patterns for the entire project.
# It includes the admin panel, the dashboard app, and authentication views.
