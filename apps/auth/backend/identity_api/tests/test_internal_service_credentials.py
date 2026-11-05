import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import RequestFactory, TestCase

from identity_api.internal import require_internal_auth
from identity_api.models import InternalServiceCredential


class InternalServiceCredentialTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.secret = "internal-service-secret-0123456789abcdef"

    def test_database_credential_accepts_only_matching_secret(self):
        credential = InternalServiceCredential(service_name="crm-backend", app_id="crm")
        credential.set_secret(self.secret)
        credential.save()

        request = self.factory.post(
            "/api/internal/auth/introspect",
            HTTP_X_INTERNAL_SERVICE="crm-backend",
            HTTP_X_INTERNAL_AUTH_SECRET=self.secret,
        )
        self.assertIsNone(require_internal_auth(request))

        rejected = self.factory.post(
            "/api/internal/auth/introspect",
            HTTP_X_INTERNAL_SERVICE="crm-backend",
            HTTP_X_INTERNAL_AUTH_SECRET="wrong-secret",
        )
        response = require_internal_auth(rejected)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["code"], "INVALID_INTERNAL_SECRET")

    def test_service_validation_endpoint_returns_verified_caller(self):
        credential = InternalServiceCredential(service_name="cable-mall-backend", app_id="cable-mall")
        credential.set_secret(self.secret)
        credential.save()

        response = self.client.post(
            "/api/internal/auth/service/validate",
            data="{}",
            content_type="application/json",
            HTTP_X_INTERNAL_SERVICE="cable-mall-backend",
            HTTP_X_INTERNAL_AUTH_SECRET=self.secret,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["serviceName"], "cable-mall-backend")
        self.assertEqual(response.json()["appId"], "cable-mall")

    def test_sync_command_rotates_and_disables_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret_file = root / "crm.secret"
            secret_file.write_text(self.secret, encoding="utf-8")
            registry_file = root / "apps.json"
            registry = {
                "schemaVersion": 1,
                "revision": "a" * 64,
                "apps": [],
                "authServices": [
                    {
                        "appId": "crm",
                        "serviceName": "crm-backend",
                        "secretFile": str(secret_file),
                        "enabled": True,
                    }
                ],
            }
            registry_file.write_text(json.dumps(registry), encoding="utf-8")
            call_command("sync_internal_services", registry=str(registry_file), verbosity=0)

            credential = InternalServiceCredential.objects.get(service_name="crm-backend")
            original_digest = credential.secret_digest
            self.assertTrue(credential.matches_secret(self.secret))

            rotated_secret = "rotated-service-secret-0123456789abcdef"
            secret_file.write_text(rotated_secret, encoding="utf-8")
            call_command("sync_internal_services", registry=str(registry_file), verbosity=0)
            credential.refresh_from_db()
            self.assertNotEqual(credential.secret_digest, original_digest)
            self.assertTrue(credential.matches_secret(rotated_secret))

            registry["revision"] = "b" * 64
            registry["authServices"] = []
            registry_file.write_text(json.dumps(registry), encoding="utf-8")
            call_command("sync_internal_services", registry=str(registry_file), verbosity=0)
            credential.refresh_from_db()
            self.assertFalse(credential.enabled)
