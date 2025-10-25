from django.test import SimpleTestCase
from django.urls import reverse, resolve
from vehicles.views import vehicle_chat_view


class VehiclesURLsTests(SimpleTestCase):
    """
    Testes unitários para o roteamento (URLs) do app `vehicles`.

    Objetivo:
    - Garantir que a URL nomeada `vehicle_chat` está configurada corretamente
      e que resolve (ou seja, aponta) para a view `vehicle_chat_view`.

    Observação:
    - Como estamos testando apenas o roteamento (sem interação com o banco de dados),
      utilizamos `SimpleTestCase` em vez de `TestCase` para tornar o teste mais leve.
    """

    def test_vehicle_chat_named_url_resolves(self):
        """
        Testa se a URL nomeada `vehicle_chat` resolve para a view correta.

        Passos:
        1. Usa `reverse("vehicle_chat")` para obter o caminho da URL a partir do nome definido em `urls.py`.
        2. Usa `resolve(url)` para obter o objeto resolver, que indica qual view é chamada para essa URL.
        3. Verifica se o resolver aponta para a função `vehicle_chat_view`.

        Esse teste garante que:
        - O nome da URL está registrado corretamente no Django.
        - Nenhum erro de importação ou rota incorreta foi configurado.
        """
        url = reverse("vehicle_chat")  # Gera o caminho da URL nomeada
        resolver = resolve(url)        # Resolve o caminho para a view real
        self.assertEqual(resolver.func, vehicle_chat_view)  # Verifica se aponta para a view esperada
