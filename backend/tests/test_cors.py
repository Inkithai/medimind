"""CORS origin parsing — FRONTEND_URL alias, trailing-slash stripping, wildcards."""

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
    origins, credentials, regex = api.parse_cors_settings("*", "")
    assert origins == ["*"]
    assert credentials is False
    assert regex is None


def test_trailing_slash_is_stripped():
    origins, credentials, regex = api.parse_cors_settings("https://app.example.com/", "")
    assert origins == ["https://app.example.com"]
    assert credentials is True
    assert regex is None


def test_frontend_url_promotes_off_star():
    origins, credentials, regex = api.parse_cors_settings("*", "https://medimind.vercel.app/")
    assert origins == ["https://medimind.vercel.app"]
    assert credentials is True
    assert regex is None


def test_cors_origins_and_frontend_url_are_merged():
    origins, credentials, regex = api.parse_cors_settings(
        "https://app.example.com, http://localhost:5173",
        "https://medimind.vercel.app/",
    )
    assert origins == [
        "https://medimind.vercel.app",
        "https://app.example.com",
        "http://localhost:5173",
    ]
    assert credentials is True
    assert regex is None


def test_duplicate_origins_are_deduped():
    origins, _credentials, _regex = api.parse_cors_settings(
        "https://app.example.com/",
        "https://app.example.com",
    )
    assert origins == ["https://app.example.com"]


def test_wildcard_pattern_becomes_origin_regex():
    origins, credentials, regex = api.parse_cors_settings("https://*.vercel.app", "")
    assert origins == []
    assert credentials is True
    assert regex == r"https://.*\.vercel\.app"


def test_wildcard_and_explicit_origins_are_combined():
    origins, credentials, regex = api.parse_cors_settings(
        "https://medimind.vercel.app, https://*.vercel.app, http://localhost:5173",
        "",
    )
    assert origins == ["https://medimind.vercel.app", "http://localhost:5173"]
    assert credentials is True
    assert regex == r"https://.*\.vercel\.app"


def test_multiple_wildcard_patterns_join_into_one_regex():
    import re

    _origins, _credentials, regex = api.parse_cors_settings(
        "https://*.vercel.app, https://*-medimind.snapdeploy.dev",
        "",
    )
    assert regex is not None
    # Assert behavior rather than the literal string: re.escape's handling of
    # "-" differs across Python versions (escaped as "\-" on 3.11, bare on 3.12+).
    assert re.fullmatch(regex, "https://medimind-murex-nu.vercel.app")
    assert re.fullmatch(regex, "https://abc-medimind.snapdeploy.dev")
    assert re.fullmatch(regex, "https://medimind.snapdeploy.dev") is None
    assert re.fullmatch(regex, "https://attacker.com") is None


def test_wildcard_in_frontend_url_is_supported():
    origins, credentials, regex = api.parse_cors_settings("*", "https://*.vercel.app/")
    assert origins == []
    assert credentials is True
    assert regex == r"https://.*\.vercel\.app"


def test_regex_cannot_be_tricked_by_suffix_lookalikes():
    regex = api._compile_origin_patterns(["https://*.vercel.app"])
    assert regex is not None
    import re

    assert re.fullmatch(regex, "https://medimind-murex-nu.vercel.app")
    assert re.fullmatch(regex, "https://medimind.vercel.app")
    assert re.fullmatch(regex, "https://evil.vercel.app.attacker.com") is None
    assert re.fullmatch(regex, "https://attacker.com") is None


def test_middleware_allows_vercel_preview_preflight():
    """End-to-end: preflight from any *.vercel.app origin passes with the
    wildcard setting — the exact failure seen with per-deployment Vercel URLs.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    origins, credentials, regex = api.parse_cors_settings("https://*.vercel.app", "")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=credentials,
        allow_origin_regex=regex,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    client = TestClient(app)

    response = client.options(
        "/api/v1/patient-snapshot",
        headers={
            "Origin": "https://medimind-murex-nu.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization, x-user-id",
        },
    )
    assert response.status_code == 200, response.text
    assert (
        response.headers["Access-Control-Allow-Origin"]
        == "https://medimind-murex-nu.vercel.app"
    )
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()

    disallowed = client.options(
        "/api/v1/patient-snapshot",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "Access-Control-Allow-Origin" not in disallowed.headers


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
