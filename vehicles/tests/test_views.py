import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from vehicles.models import Vehicle
from vehicles import views as vehicle_views


class VehicleChatViewTests(TestCase):
    """
    Testes de integração focados na view de chat de veículos.

    O que cobrimos aqui:
      - Utilitários de parsing (parse_filters) usados pela view.
      - Fluxo GET da view de chat (render simples).
      - Fluxo POST da view de chat:
          * Recebe a mensagem do usuário
          * Converte texto em filtros
          * Aplica filtros ao catálogo
          * Retorna JSON padronizado (reply, suggestions, items, total_matches, filters_applied, generated_at)

    Observações:
      - O GET não depende de template existente graças ao uso de mock em `render`.
      - Os testes criam um mini-catálogo de veículos em setUp para validar os filtros.
    """

    def setUp(self):
        """
        Cria um cliente de teste e popula um catálogo mínimo.

        Catálogo:
        - Jeep Compass 2021, SUV, automático, flex (VIN001) -> esperado aparecer quando filtrar SUV automático
        - Fiat Argo 2019, Hatch, manual, flex (VIN002)
        """
        self.client = Client()

        # Veículo candidato principal para nossos filtros de exemplo (SUV + Automática)
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

        # Segundo veículo para garantir que a view sabe filtrar
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

    # --------------------------------------------------------------------------
    # Testes de utilidades: parse_filters
    # --------------------------------------------------------------------------

    def test_parse_filters_price_year_doors(self):
        """
        Garante que `parse_filters` extrai corretamente:
        - carroceria (SUV)
        - transmissão (Automática)
        - ano mínimo (2020)
        - número de portas (4)
        - preço máximo (até 120.000)
        """
        msg = "Quero SUV automático até 120 mil, a partir de 2020, com 4 portas"
        f = vehicle_views.parse_filters(msg)

        self.assertEqual(f["body_type"], "SUV")
        self.assertEqual(f["transmission"], "Automática")
        self.assertEqual(f["year_min"], 2020)
        self.assertEqual(f["doors"], 4)

        # preço vira Decimal ~ 120000.00 (validamos o inteiro por simplicidade)
        self.assertIsNotNone(f["price_max"])
        self.assertEqual(int(f["price_max"]), 120000)

    def test_parse_filters_year_range_and_fuel(self):
        """
        Valida extração de:
        - carroceria (Sedan)
        - combustível (gasolina)
        - faixa de anos como tupla (2017, 2022)
        - preço máximo presente no texto ("até R$ 95.000")
        """
        msg = "Sedan gasolina 2017-2022 até R$ 95.000"
        f = vehicle_views.parse_filters(msg)

        self.assertEqual(f["body_type"], "Sedan")
        self.assertEqual(f["fuel"], "gasolina")
        self.assertEqual(f["year_range"], (2017, 2022))
        self.assertIsNotNone(f["price_max"])

    # --------------------------------------------------------------------------
    # View: GET sem depender de template
    # --------------------------------------------------------------------------

    @patch("vehicles.views.render")
    def test_get_returns_200_without_template_dependency(self, mock_render):
        """
        Evita que o teste falhe por falta do template físico em disco.

        Estratégia:
        - `patch` em `vehicles.views.render` para retornar uma HttpResponse "ok"
        - Realiza GET em `vehicle_chat` e confirma 200
        - Garante que `render` foi chamado (view renderiza a página do chat)
        """
        from django.http import HttpResponse

        mock_render.return_value = HttpResponse("ok")

        url = reverse("vehicle_chat")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        mock_render.assert_called_once()

    # --------------------------------------------------------------------------
    # View: POST com filtros
    # --------------------------------------------------------------------------

    def test_post_filters_and_returns_json(self):
        """
        Valida o fluxo POST: aplica filtros a partir do texto e retorna JSON canônico.

        Entrada:
        - message: "Procuro SUV automático até R$ 120.000"

        Saída esperada (chaves):
        - reply: texto amigável para o usuário
        - suggestions: lista de sugestões de próximos passos (quando houver)
        - items: lista de veículos serializados
        - total_matches: inteiro com a quantidade
        - filters_applied: filtros reconhecidos e aplicados
        - generated_at: timestamp ISO

        Também validamos que:
        - O VIN "VIN001" (Jeep Compass 2021) aparece nos resultados
        - Os filtros aplicados incluem carroceria e transmissão corretas
        """
        url = reverse("vehicle_chat")
        payload = {
            "message": "Procuro SUV automático até R$ 120.000",
            "history": [],  # histórico opcional, se a view usar
        }

        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()

        # Estrutura mínima do contrato JSON retornado pela view
        for key in ["reply", "suggestions", "items", "total_matches", "filters_applied", "generated_at"]:
            self.assertIn(key, data)

        # Deve trazer pelo menos o Compass como candidato (VIN001)
        items = data["items"]
        self.assertTrue(any(i["vin"] == "VIN001" for i in items))

        # Filtros aplicados devem indicar body_type e transmissão
        self.assertEqual(data["filters_applied"].get("body_type"), "SUV")
        self.assertEqual(data["filters_applied"].get("transmission"), "Automática")

    def test_post_when_no_matches_falls_back_to_recent_catalog(self):
        """
        Quando não existir nenhum match exato,
        a view deve retornar um catálogo recente (fallback não-vazio).

        Entrada propositalmente “impossível”:
        - elétrico + diesel + cupê + 2 portas + até 10 mil

        Verificações:
        - status 200
        - total_matches >= 1 (algum fallback retornado)
        - items é uma lista
        """
        url = reverse("vehicle_chat")
        payload = {
            "message": "Quero elétrico diesel cupê 2 portas até R$ 10.000",
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
