"""SPA catchall must not serve files outside meeting_ai_frontend/dist.
Run: python tests/test_spa_path_traversal.py  (needs dist/ built)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
import main

assert os.path.isdir(main.frontend_path), "build the frontend first"
c = TestClient(main.app)
for accept in ("*/*", "text/html"):  # catchall route, then HTML middleware
    for p in ("/..%2F..%2Fmain.py", "/..%2f..%2frequirements.txt", "/..%2F..%2F.env",
              "/%2E%2E%2F%2E%2E%2Fmain.py", "/..%5C..%5Cmain.py"):
        r = c.get(p, headers={"accept": accept})
        assert "import uvicorn" not in r.text and "fastapi" not in r.text.lower()[:200], (accept, p)
        assert r.headers["content-type"].startswith("text/html"), (accept, p, r.headers["content-type"])
r = c.get("/index.html")
assert r.status_code == 200 and "<html" in r.text.lower()
print("OK: traversal blocked, index still served")
