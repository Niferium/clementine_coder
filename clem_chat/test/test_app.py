"""
test_app.py — pytest suite for app.py

Run with:
    pytest test_app.py -v
"""

import pytest
import json
from unittest.mock import MagicMock, patch


class TestExtractCodeBlocks:
    """Unit tests for App.extract_code_blocks()."""

    @pytest.fixture
    def app_instance(self):
        with (
            patch("app.config") as mock_cfg,
            patch("app.Agent"),
            patch("app.CORS"),
        ):
            mock_cfg.MAX_TOKENS = 512
            mock_cfg.MAIN_MODEL = "model-a"

            from app import App
            yield App()

    # --- basic extraction --------------------------------------------------

    def test_single_python_block(self, app_instance):
        text = "```python\nprint('hello')\n```"
        blocks = app_instance.extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["language"] == "python"
        assert blocks[0]["extension"] == "py"
        assert "print('hello')" in blocks[0]["code"]

    def test_single_javascript_block(self, app_instance):
        text = "```javascript\nconsole.log('hi');\n```"
        blocks = app_instance.extract_code_blocks(text)
        assert blocks[0]["language"] == "javascript"
        assert blocks[0]["extension"] == "js"

    def test_multiple_blocks(self, app_instance):
        text = (
            "```python\nx = 1\n```\n"
            "Some text in between.\n"
            "```bash\necho hello\n```"
        )
        blocks = app_instance.extract_code_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["language"] == "python"
        assert blocks[1]["language"] == "bash"

    def test_no_code_blocks(self, app_instance):
        blocks = app_instance.extract_code_blocks("Plain text, no code.")
        assert blocks == []

    def test_unknown_language_uses_lang_as_ext(self, app_instance):
        text = "```brainfuck\n++++.\n```"
        blocks = app_instance.extract_code_blocks(text)
        assert blocks[0]["extension"] == "brainfuck"

    def test_no_language_tag_defaults_to_txt(self, app_instance):
        text = "```\nsome raw text\n```"
        blocks = app_instance.extract_code_blocks(text)
        assert blocks[0]["extension"] == "txt"

    def test_language_aliases(self, app_instance):
        cases = [
            ("py",  "py"),
            ("js",  "js"),
            ("ts",  "ts"),
            ("sh",  "sh"),
            ("c#",  "cs"),
            ("c++", "cpp"),
        ]
        for lang, expected_ext in cases:
            blocks = app_instance.extract_code_blocks(f"```{lang}\ncode\n```")
            assert blocks[0]["extension"] == expected_ext, f"Failed for lang={lang}"

    def test_code_content_is_preserved(self, app_instance):
        code = "def foo():\n    return 42"
        blocks = app_instance.extract_code_blocks(f"```python\n{code}\n```")
        assert blocks[0]["code"] == code

    def test_multiline_code_block(self, app_instance):
        text = "```sql\nSELECT *\nFROM users\nWHERE id = 1;\n```"
        blocks = app_instance.extract_code_blocks(text)
        assert blocks[0]["language"] == "sql"
        assert "FROM users" in blocks[0]["code"]


class TestFlaskRoutes:
    """Integration-style tests for the Flask endpoints."""

    @pytest.fixture
    def client(self):
        with (
            patch("app.config") as mock_cfg,
            patch("app.Agent") as MockAgent,
            patch("app.CORS"),
        ):
            mock_cfg.MAX_TOKENS = 512
            mock_cfg.MAIN_MODEL = "model-a"

            mock_agent = MockAgent.return_value
            mock_agent.get_status.return_value = {"model": "model-a", "loaded": True}
            mock_agent.chat.return_value = "Hello from agent"
            mock_agent.stream_chat.return_value = iter(["Hello", " world"])

            from app import App
            instance = App()
            instance.app.config["TESTING"] = True
            yield instance.app.test_client(), mock_agent

    # --- /api/health -------------------------------------------------------

    def test_health_returns_ok(self, client):
        test_client, _ = client
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        assert json.loads(resp.data)["status"] == "ok"

    def test_health_includes_agent_status(self, client):
        test_client, _ = client
        resp = test_client.get("/api/health")
        assert "model" in json.loads(resp.data)

    # --- /api/chat (non-streaming) -----------------------------------------

    def test_chat_no_stream_success(self, client):
        test_client, _ = client
        payload = {"messages": [{"role": "user", "content": "hi"}], "stream": False}
        resp = test_client.post("/api/chat", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        assert json.loads(resp.data)["response"] == "Hello from agent"

    def test_chat_missing_messages_returns_400(self, client):
        test_client, _ = client
        resp = test_client.post("/api/chat", data=json.dumps({"stream": False}), content_type="application/json")
        assert resp.status_code == 400

    def test_chat_agent_exception_returns_500(self, client):
        test_client, mock_agent = client
        mock_agent.chat.side_effect = RuntimeError("model exploded")
        payload = {"messages": [{"role": "user", "content": "hi"}], "stream": False}
        resp = test_client.post("/api/chat", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 500
        assert json.loads(resp.data)["status"] == "error"

    # --- /api/load-model ---------------------------------------------------

    def test_load_model_accepts_post(self, client):
        test_client, mock_agent = client
        mock_agent.load = MagicMock()
        payload = {"model": "some-model"}
        resp = test_client.post("/api/load-model", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "loading"
        assert data["model"] == "some-model"