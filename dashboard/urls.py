from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('logout/', views.logout_view, name='logout'),
]
# This file defines the URL patterns for the dashboard app.
# It maps the root URL of the dashboard to the `dashboard_view` function in the views module.