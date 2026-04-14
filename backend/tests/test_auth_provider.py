import unittest
import uuid

from jose import jwt

from app.auth.platform_deps import create_access_token
from app.auth.provider import authenticate_token_via_provider
from app.config import settings


class TestAuthProvider(unittest.IsolatedAsyncioTestCase):
    async def test_local_provider_accepts_local_token(self):
        prev = settings.auth_provider
        try:
            settings.auth_provider = "local"
            token = create_access_token(user_id=uuid.uuid4(), email="owner@example.com", role="owner")
            out = await authenticate_token_via_provider(None, token)  # type: ignore[arg-type]
            self.assertEqual(out.role, "owner")
            self.assertEqual(out.email, "owner@example.com")
        finally:
            settings.auth_provider = prev

    async def test_saml_provider_accepts_bridge_token(self):
        prev = settings.auth_provider
        try:
            settings.auth_provider = "saml"
            token = jwt.encode(
                {"sub": "owner@example.com", "email": "owner@example.com", "role": "owner", "typ": "saml_bridge"},
                settings.secret_key,
                algorithm="HS256",
            )
            out = await authenticate_token_via_provider(None, token)  # type: ignore[arg-type]
            self.assertEqual(out.role, "owner")
            self.assertEqual(out.email, "owner@example.com")
        finally:
            settings.auth_provider = prev


if __name__ == "__main__":
    unittest.main()
