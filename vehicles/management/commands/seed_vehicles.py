# vehicles/management/commands/seed_vehicles.py
from django.core.management.base import BaseCommand
from django.db import transaction
from faker import Faker
from decimal import Decimal
import random

from vehicles.models import Vehicle

BRANDS = [
    ("Volkswagen", ["Gol", "Polo", "T-Cross", "Nivus"]),
    ("Chevrolet", ["Onix", "Tracker", "S10", "Cruze"]),
    ("Fiat", ["Argo", "Cronos", "Toro", "Pulse"]),
    ("Toyota", ["Corolla", "Yaris", "Hilux", "RAV4"]),
    ("Hyundai", ["HB20", "Creta", "i30", "Tucson"]),
    ("Honda", ["Civic", "City", "HR-V", "Fit"]),
    ("Ford", ["Ka", "Ranger", "Fusion", "Territory"]),
]

FUEL = ["gasolina", "alcool", "diesel", "flex", "eletrico", "hibrido"]
TRANS = ["manual", "automatica", "cvt"]
BODY = ["hatch", "sedan", "suv", "pickup", "coupe", "wagon"]
COLORS = ["preto", "branco", "prata", "cinza", "azul", "vermelho"]

# VIN real não usa I, O, Q. Vamos gerar 17 chars sem esses.
_VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"

def unique_vin():
    return "".join(random.choices(_VIN_CHARS, k=17))

class Command(BaseCommand):
    help = "Popula o banco com veículos fake."

    def add_arguments(self, parser):
        parser.add_argument("--min", "--n", dest="n", type=int, default=100,
                            help="Quantidade de veículos a criar (alias: --min, --n)")

    @transaction.atomic
    def handle(self, *args, **options):
        fake = Faker("pt_BR")
        target = options["n"]
        created = 0
        vins_lote = set()

        for _ in range(target):
            brand, models = random.choice(BRANDS)
            model = random.choice(models)
            year = random.randint(2005, 2025)
            engine = random.choice(["1.0", "1.6", "2.0", "1.0 TSI", "1.5 Turbo", "Elétrico 150kW"])
            fuel = random.choice(FUEL)
            color = random.choice(COLORS)
            mileage = random.randint(0, 200_000)
            doors = random.choice([2, 4])
            trans = random.choice(TRANS)
            body = random.choice(BODY)
            price = Decimal(f"{random.uniform(35_000, 350_000):.2f}")

            vin = unique_vin()
            # Evita colisão tanto no banco quanto no lote atual
            while vin in vins_lote or Vehicle.objects.filter(vin=vin).exists():
                vin = unique_vin()
            vins_lote.add(vin)

            Vehicle.objects.create(
                brand=brand,
                model=model,
                year=year,
                engine=engine,
                fuel_type=fuel,
                color=color,
                mileage_km=mileage,
                doors=doors,
                transmission=trans,
                body_type=body,
                price=price,
                vin=vin,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Veículos criados: {created}"))
