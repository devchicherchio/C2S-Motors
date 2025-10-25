from django.test import TestCase
from django.db import IntegrityError
from vehicles.models import Vehicle


class VehicleModelTests(TestCase):
    """
    Testes unitários para o modelo Vehicle.

    Objetivo:
    - Garantir que o comportamento do modelo (campos, constraints e ordenação)
      está funcionando corretamente.
    - Cobrir casos básicos como __str__, valores padrão e unicidade do VIN.
    """

    def setUp(self):
        """
        Configuração inicial executada antes de cada teste.

        Aqui criamos um veículo base (Toyota Corolla 2021) para ser usado nos testes.
        """
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
        """
        Testa a representação textual (__str__) do modelo.

        Esperado:
        - O método __str__ deve retornar uma string no formato:
          "<marca> <modelo> <ano>"
        Exemplo: "Toyota Corolla 2021"
        """
        self.assertEqual(str(self.v1), "Toyota Corolla 2021")

    def test_doors_default(self):
        """
        Testa se o campo `doors` (número de portas) possui valor padrão igual a 4.

        Caso o campo não seja especificado na criação do veículo,
        ele deve automaticamente assumir o valor padrão 4.
        """
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
        self.assertEqual(v.doors, 4)  # Verifica se o padrão foi aplicado corretamente.

    def test_created_at_ordering_desc(self):
        """
        Testa se a ordenação padrão do modelo está correta (ordem decrescente de criação).

        Premissa:
        - O modelo Vehicle define Meta.ordering = ["-created_at"], ou seja,
          os registros mais recentes devem vir primeiro na consulta.

        Passos:
        1. Cria um segundo veículo (HR-V 2022).
        2. Faz uma consulta Vehicle.objects.all().first().
        3. Verifica se o primeiro resultado é o veículo mais recente criado.
        """
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

        first = Vehicle.objects.all().first()  # Deve ser o último inserido
        self.assertEqual(first.id, v2.id)  # Verifica se o ordering está funcionando.

    def test_vin_unique_constraint(self):
        """
        Testa a restrição de unicidade do campo `vin`.

        Premissa:
        - O campo VIN (chassi) deve ser único no banco de dados.

        Passos:
        1. Tenta criar um novo veículo com o mesmo VIN do existente.
        2. Deve disparar um erro de integridade (IntegrityError).
        """
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
                vin="9BWZZZ377VT004251",  # VIN duplicado do setUp()
            )
