"""
Shared test bootstrap.

Importing most backend modules requires provider/storage configuration to be
present: ``llm_provider`` raises at import time when no API key is set, and
``db``/``storage`` expect Supabase and Cloudinary variables. Individual test
modules used to each set those variables at module scope, which worked only
because *some* alphabetically-earlier module happened to run first in the
same process. A module that did not set them — ``test_ocr_service.py`` — then
passed in a full-suite run but failed on its own with a
``GROQ_API_KEY is not set`` error that had nothing to do with what it tests.

pytest imports ``conftest.py`` before collecting any test module, so setting
the defaults here makes every file runnable on its own:

    python -m pytest tests/test_ocr_service.py

``setdefault`` throughout: a real key already exported in the environment
(for example when running the OpenFDA or embedding tests against live
services) is never overwritten by a dummy.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# LLM provider — import-time guarded in llm_provider.py.
os.environ.setdefault("LLM_PROVIDER", "groq")
os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

# Supabase / storage — read when db.py and storage.py are imported.
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")

# Auth — anonymous-session tokens are signed with this.
os.environ.setdefault("JWT_SECRET", "dummy-test-secret-not-used-in-production")

# Never download the embedding model during a test run.
os.environ.setdefault("PRELOAD_EMBEDDING_MODEL", "false")

# OCR must be decided by the machine running the tests, not by a developer's
# shell: an exported MEDIMIND_TESSERACT_CMD would otherwise flip the
# availability tests. Individual tests set it explicitly when they mean to.
os.environ.pop("MEDIMIND_TESSERACT_CMD", None)
os.environ.pop("TESSERACT_CMD", None)
