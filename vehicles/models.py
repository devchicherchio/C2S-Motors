# vehicles/models.py
from django.db import models

class Vehicle(models.Model):
    brand = models.CharField("Marca", max_length=50)
    model = models.CharField("Modelo", max_length=80)
    year = models.PositiveIntegerField("Ano")
    engine = models.CharField("Motorização", max_length=40)           # ex: 1.0 Turbo
    fuel_type = models.CharField("Combustível", max_length=30)         # ex: Flex, Gasolina, Diesel, Elétrico, Híbrido
    color = models.CharField("Cor", max_length=30)
    mileage_km = models.PositiveIntegerField("Quilometragem")
    doors = models.PositiveSmallIntegerField("Portas", default=4)
    transmission = models.CharField("Transmissão", max_length=20)      # ex: Manual/Automática/CVT
    body_type = models.CharField("Carroceria", max_length=30)          # ex: Sedan, Hatch, SUV, Picape
    price = models.DecimalField("Preço", max_digits=12, decimal_places=2)
    vin = models.CharField("VIN/Chassi", max_length=32, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.brand} {self.model} {self.year}"
