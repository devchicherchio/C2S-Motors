# vehicles/admin.py
from django.contrib import admin
from .models import Vehicle

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("brand","model","year","fuel_type","transmission","price","mileage_km", "body_type")
    search_fields = ("brand","model","vin","fuel_type","body_type","color")
    list_filter = ("brand","fuel_type","transmission","body_type","year","color")
