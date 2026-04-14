import unittest
import uuid
from types import SimpleNamespace

from app.routers.admin import _request_fingerprint_for_registry_action
from app.services import artifact_store


class TestArtifactPolicy(unittest.TestCase):
    def test_artifact_allowed_s3_bucket_allowlist(self):
        prev_schemes = artifact_store.settings.artifact_allowed_schemes
        prev_buckets = artifact_store.settings.artifact_s3_allowed_buckets
        try:
            artifact_store.settings.artifact_allowed_schemes = "file,s3"
            artifact_store.settings.artifact_s3_allowed_buckets = "bankai-models"
            self.assertTrue(artifact_store._artifact_allowed("s3://bankai-models/path/model.joblib"))  # pylint: disable=protected-access
            self.assertFalse(artifact_store._artifact_allowed("s3://other-bucket/path/model.joblib"))  # pylint: disable=protected-access
            self.assertFalse(artifact_store._artifact_allowed("https://example.com/model.joblib"))  # pylint: disable=protected-access
        finally:
            artifact_store.settings.artifact_allowed_schemes = prev_schemes
            artifact_store.settings.artifact_s3_allowed_buckets = prev_buckets


class TestLifecycleFingerprint(unittest.TestCase):
    def test_fingerprint_stable_for_same_action(self):
        rid = uuid.uuid4()
        row = SimpleNamespace(
            id=rid,
            tenant_id=uuid.uuid4(),
            model_type="fraud",
            version="v1",
            status="shadow",
        )
        a = _request_fingerprint_for_registry_action(row, "activate")
        b = _request_fingerprint_for_registry_action(row, "activate")
        c = _request_fingerprint_for_registry_action(row, "rollback")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
