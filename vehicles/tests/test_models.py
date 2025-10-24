from django.test import TestCase
from django.db import IntegrityError
from vehicles.models import Vehicle

class VehicleModelTests(TestCase):
    def setUp(self):
        self.v1 = Vehicle.objects.create(
            brand="Toyota",
            model="Corolla",
            year=2021,
            engine="2.0",
            fuel_type="gasolina",
            color="Prata",
            mileage_km=30000,
            doors=4,
            transmission="Automática",
            body_type="Sedan",
            price="115000.00",
            vin="9BWZZZ377VT004251",
        )

    def test_str_representation(self):
        self.assertEqual(str(self.v1), "Toyota Corolla 2021")

    def test_doors_default(self):
        v = Vehicle.objects.create(
            brand="VW",
            model="Gol",
            year=2018,
            engine="1.6",
            fuel_type="flex",
            color="Branco",
            mileage_km=60000,
            transmission="Manual",
            body_type="Hatch",
            price="42000.00",
            vin="9BWZZZ377VT004252",
        )
        self.assertEqual(v.doors, 4)

    def test_created_at_ordering_desc(self):
        # Criar segundo depois do primeiro: ordering = ["-created_at"] deve trazer o segundo primeiro
        v2 = Vehicle.objects.create(
            brand="Honda",
            model="HR-V",
            year=2022,
            engine="1.5 Turbo",
            fuel_type="gasolina",
            color="Preto",
            mileage_km=10000,
            doors=4,
            transmission="CVT",
            body_type="SUV",
            price="148000.00",
            vin="9BWZZZ377VT004253",
        )
        first = Vehicle.objects.all().first()
        self.assertEqual(first.id, v2.id)

    def test_vin_unique_constraint(self):
        with self.assertRaises(IntegrityError):
            Vehicle.objects.create(
                brand="Toyota",
                model="Corolla",
                year=2020,
                engine="2.0",
                fuel_type="gasolina",
                color="Prata",
                mileage_km=20000,
                doors=4,
                transmission="Automática",
                body_type="Sedan",
                price="109000.00",
                vin="9BWZZZ377VT004251",  # duplicado
            )
