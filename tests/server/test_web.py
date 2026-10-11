import shutil
import subprocess

import pytest


def test_page_and_assets_are_served(client):
    page = client.get("/").text
    assert "chessground@9.2.1" in page
    assert "/static/app.js" in page
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_app_js_parses(tmp_path):
    from chess_mcp.server.app import WEB_DIR

    module = tmp_path / "app.mjs"
    module.write_text((WEB_DIR / "app.js").read_text())
    subprocess.run(["node", "--check", str(module)], check=True)
