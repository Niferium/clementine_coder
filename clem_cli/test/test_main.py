"""
test_main.py — pytest suite for main.py

Run with:
    pytest test_main.py -v
"""

import pytest
from unittest.mock import MagicMock, patch


def make_mock_sys_prompt():
    """Return a mock sys_prompt module with stub callables."""
    mock = MagicMock()
    mock.SYSTEM_PROMPT_SENIOR_SOFTWARE_ENGINEER.return_value = "engineer prompt"
    mock.SYSTEM_PROMPT_PYTHON.return_value = "python prompt"
    mock.SYSTEM_PROMPT_CHAT_INTERFACE_MAKER.return_value = "cim prompt"
    return mock


class TestGetPromptCategory:
    """Unit tests for Main.get_prompt_category()."""

    @pytest.fixture
    def main_instance(self):
        with (
            patch("main.Logger"),
            patch("main.config") as mock_cfg,
            patch("main.load"),
            patch("main.sys_prompt", new=make_mock_sys_prompt()) as mock_prompt,
        ):
            mock_cfg.MAIN_MODEL = "model-a"
            mock_cfg.ROUTER_MODEL = "model-b"
            mock_cfg.MAX_TOKENS = 512
            mock_cfg.ROUTER_TOKENS = 128

            from main import Main
            instance = Main()
            instance.sys_prompt = mock_prompt
            yield instance

    # --- "use engineer" triggers -------------------------------------------

    def test_use_engineer_exact(self, main_instance):
        result = main_instance.get_prompt_category("use engineer to fix this")
        assert result == "engineer prompt"

    def test_use_engineer_case_insensitive(self, main_instance):
        result = main_instance.get_prompt_category("USE ENGINEER please")
        assert result == "engineer prompt"

    # --- "use python" triggers ---------------------------------------------

    def test_use_python_exact(self, main_instance):
        result = main_instance.get_prompt_category("use python for this task")
        assert result == "python prompt"

    def test_use_python_mixed_case(self, main_instance):
        result = main_instance.get_prompt_category("Use Python here")
        assert result == "python prompt"

    # --- "use cim" triggers ------------------------------------------------

    def test_use_cim_exact(self, main_instance):
        result = main_instance.get_prompt_category("use cim for the interface")
        assert result == "cim prompt"

    def test_use_cim_upper(self, main_instance):
        result = main_instance.get_prompt_category("USE CIM now")
        assert result == "cim prompt"

    # --- default / fallback ------------------------------------------------

    def test_default_prompt_on_generic_input(self, main_instance):
        result = main_instance.get_prompt_category("just a normal question")
        assert result == "engineer prompt"

    def test_default_prompt_empty_string(self, main_instance):
        result = main_instance.get_prompt_category("")
        assert result == "engineer prompt"

    def test_default_prompt_unrelated_keyword(self, main_instance):
        result = main_instance.get_prompt_category("use database for something")
        assert result == "engineer prompt"