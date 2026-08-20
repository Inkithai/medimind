"""CORS origin parsing — FRONTEND_URL alias and trailing-slash stripping."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
os.environ.setdefault("JWT_SECRET", "dummy")

import api  # noqa: E402


def test_default_star_disables_credentials():
    origins, credentials = api.parse_cors_settings("*", "")
    assert origins == ["*"]
    assert credentials is False


def test_trailing_slash_is_stripped():
    origins, credentials = api.parse_cors_settings("https://app.example.com/", "")
    assert origins == ["https://app.example.com"]
    assert credentials is True


def test_frontend_url_promotes_off_star():
    origins, credentials = api.parse_cors_settings("*", "https://medimind.vercel.app/")
    assert origins == ["https://medimind.vercel.app"]
    assert credentials is True


def test_cors_origins_and_frontend_url_are_merged():
    origins, credentials = api.parse_cors_settings(
        "https://app.example.com, http://localhost:5173",
        "https://medimind.vercel.app/",
    )
    assert origins == [
        "https://medimind.vercel.app",
        "https://app.example.com",
        "http://localhost:5173",
    ]
    assert credentials is True


def test_duplicate_origins_are_deduped():
    origins, _credentials = api.parse_cors_settings(
        "https://app.example.com/",
        "https://app.example.com",
    )
    assert origins == ["https://app.example.com"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
