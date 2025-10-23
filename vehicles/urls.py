# vehicles/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.vehicle_chat_view, name="vehicle_chat"),
]
