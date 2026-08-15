"""Keeps the About page honest about the backend.

The About / technical overview page documents the REST surface. Documentation
that drifts from the code is worse than none — a judge or developer testing a
documented endpoint that 404s loses trust in everything else on the page.

This test parses the endpoint table straight out of the frontend i18n
dictionary and asserts, against the live FastAPI app, that:

  * every documented path+method actually exists
  * nothing sensitive (keys, secrets, env var values) is published
  * routes the page claims need no auth really are public
"""

import os
import re
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


_ABOUT_COPY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend",
    "src",
    "pages",
    "AboutPage.tsx",
)

# The endpoint table lives in AboutPage.tsx (paths and HTTP verbs are code,
# not translatable copy); the human descriptions live in the i18n catalogs.
_ENDPOINT_RE = re.compile(
    r'\{\s*method:\s*"(?P<method>[A-Z]+)",\s*path:\s*"(?P<path>[^"]+)"'
)


def _documented_endpoints():
    """(method, path) pairs the About page advertises."""
    with open(_ABOUT_COPY_PATH, encoding="utf-8") as handle:
        source = handle.read()
    found = [(m.group("method"), m.group("path")) for m in _ENDPOINT_RE.finditer(source)]
    assert found, "no endpoints parsed from AboutPage.tsx — did the table format change?"
    return found


def _real_routes():
    """(method, path) pairs FastAPI actually serves."""
    routes = set()
    for route in api.app.routes:
        for method in getattr(route, "methods", set()) or set():
            routes.add((method, getattr(route, "path", "")))
    return routes


def test_every_documented_endpoint_exists():
    real = _real_routes()
    missing = [pair for pair in _documented_endpoints() if pair not in real]
    assert not missing, f"About page documents endpoints that do not exist: {missing}"


def test_documented_paths_use_the_versioned_api_prefix():
    for method, path in _documented_endpoints():
        assert path.startswith("/api/v1/"), (method, path)


def test_no_secrets_or_credentials_are_published():
    """The page must never leak a key, token, or configured value."""
    with open(_ABOUT_COPY_PATH, encoding="utf-8") as handle:
        source = handle.read()

    # Real key shapes, and any env var being given a value.
    forbidden_patterns = [
        r"gsk_[A-Za-z0-9]{10,}",          # Groq
        r"AIza[A-Za-z0-9_\-]{10,}",       # Google
        r"sk-[A-Za-z0-9]{10,}",           # OpenAI
        r"eyJ[A-Za-z0-9_\-]{10,}",        # JWT
        r"[A-Z_]{4,}_(?:KEY|SECRET|TOKEN|PASSWORD)\s*[:=]\s*[\"'][^\"']+[\"']",
        r"postgres(?:ql)?://",
        r"\.supabase\.co",
    ]
    for pattern in forbidden_patterns:
        match = re.search(pattern, source)
        assert match is None, f"possible secret published on the About page: {match.group(0)!r}"


def test_public_routes_really_are_public():
    """The page tells readers these two need no authentication."""
    for path in ("/api/v1/health", "/api/v1/anonymous/session"):
        route = next(r for r in api.app.routes if getattr(r, "path", "") == path)
        dependencies = getattr(route, "dependant", None)
        assert dependencies is not None
        names = {
            getattr(sub.call, "__name__", "")
            for sub in dependencies.dependencies
        }
        assert "get_current_user" not in names, f"{path} is documented as public but requires auth"


def test_authenticated_routes_are_actually_protected():
    """Conversely, everything else documented must require a verified user."""
    public = {"/api/v1/health", "/api/v1/anonymous/session"}
    for method, path in _documented_endpoints():
        if path in public:
            continue
        route = next(
            r
            for r in api.app.routes
            if getattr(r, "path", "") == path and method in (getattr(r, "methods", set()) or set())
        )
        names = {
            getattr(sub.call, "__name__", "")
            for sub in route.dependant.dependencies
        }
        assert "get_current_user" in names, f"{method} {path} is documented but unprotected"


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
