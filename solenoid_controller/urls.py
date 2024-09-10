from django.urls import path
from . import views

urlpatterns = [
    path('', views.control_form, name='control_form'),
    path('settings/', views.settings_form, name='settings_form'),
    path('submit_settings/', views.submit_settings, name='submit_settings'),
    path('submit/', views.submit_control, name='submit_control'),
]