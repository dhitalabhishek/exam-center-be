from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Institute


class InstituteAPITests(APITestCase):
    def test_create_institute(self):
        url = reverse("institute-list")
        data = {
            "name": "Test Institute",
            "email": "test@inst.edu",
            "description": "A test institute.",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)  # noqa: PT009
        self.assertEqual(Institute.objects.count(), 1) # noqa: PT009
        self.assertEqual(Institute.objects.get().name, "Test Institute") # noqa: PT009
