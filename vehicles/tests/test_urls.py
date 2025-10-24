from django.test import SimpleTestCase
from django.urls import reverse, resolve
from vehicles.views import vehicle_chat_view

class VehiclesURLsTests(SimpleTestCase):
    def test_vehicle_chat_named_url_resolves(self):
        url = reverse("vehicle_chat")
        resolver = resolve(url)
        self.assertEqual(resolver.func, vehicle_chat_view)
