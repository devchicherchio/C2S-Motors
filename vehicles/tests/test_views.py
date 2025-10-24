import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from vehicles.models import Vehicle
from vehicles import views as vehicle_views

class VehicleChatViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Catálogo base
        self.suv_ok = Vehicle.objects.create(
            brand="Jeep",
            model="Compass",
            year=2021,
            engine="1.3 Turbo",
            fuel_type="flex",
            color="Preto",
            mileage_km=25000,
            doors=4,
            transmission="Automática",
            body_type="SUV",
            price="119000.00",
            vin="VIN001",
        )
        Vehicle.objects.create(
            brand="Fiat",
            model="Argo",
            year=2019,
            engine="1.0",
            fuel_type="flex",
            color="Branco",
            mileage_km=40000,
            doors=4,
            transmission="Manual",
            body_type="Hatch",
            price="48000.00",
            vin="VIN002",
        )

    # --------- Testes de utilidades: parse_filters ----------
    def test_parse_filters_price_year_doors(self):
        msg = "Quero SUV automático até 120 mil, a partir de 2020, com 4 portas"
        f = vehicle_views.parse_filters(msg)
        self.assertEqual(f["body_type"], "SUV")
        self.assertEqual(f["transmission"], "Automática")
        self.assertEqual(f["year_min"], 2020)
        self.assertEqual(f["doors"], 4)
        # preço vira Decimal ~ 120000.00
        self.assertIsNotNone(f["price_max"])
        self.assertEqual(int(f["price_max"]), 120000)

    def test_parse_filters_year_range_and_fuel(self):
        msg = "Sedan gasolina 2017-2022 até R$ 95.000"
        f = vehicle_views.parse_filters(msg)
        self.assertEqual(f["body_type"], "Sedan")
        self.assertEqual(f["fuel"], "gasolina")
        self.assertEqual(f["year_range"], (2017, 2022))
        self.assertIsNotNone(f["price_max"])

    # --------- View: GET sem depender de template ----------
    @patch("vehicles.views.render")
    def test_get_returns_200_without_template_dependency(self, mock_render):
        # Evita falhar se 'vehicles/chat.html' não existir no ambiente de teste
        from django.http import HttpResponse
        mock_render.return_value = HttpResponse("ok")
        url = reverse("vehicle_chat")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        mock_render.assert_called_once()

    # --------- View: POST com filtros ----------
    def test_post_filters_and_returns_json(self):
        url = reverse("vehicle_chat")
        payload = {
            "message": "Procuro SUV automático até R$ 120.000",
            "history": [],
        }
        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        # Estrutura básica:
        for key in ["reply", "suggestions", "items", "total_matches", "filters_applied", "generated_at"]:
            self.assertIn(key, data)

        # Deve trazer pelo menos o Compass como candidato
        items = data["items"]
        self.assertTrue(any(i["vin"] == "VIN001" for i in items))

        # Filtros aplicados devem indicar body_type e transmissão
        self.assertEqual(data["filters_applied"].get("body_type"), "SUV")
        self.assertEqual(data["filters_applied"].get("transmission"), "Automática")

    def test_post_when_no_matches_falls_back_to_recent_catalog(self):
        url = reverse("vehicle_chat")
        payload = {
            "message": "Quero elétrico diesel cupê 2 portas até R$ 10.000",  # forçando algo improvável
            "history": [],
        }
        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Como não há match, a view cai para o catálogo recente (não-vazio)
        self.assertGreaterEqual(data["total_matches"], 1)
        self.assertIsInstance(data["items"], list)
