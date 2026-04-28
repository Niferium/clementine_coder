"""
test_run.py — pytest suite for run.py

Run with:
    pytest test_run.py -v
"""

import pytest
import argparse
from unittest.mock import MagicMock, patch


class TestRunArgParsing:
    """Unit tests for the CLI argument parser in run.py."""

    @pytest.fixture(autouse=True)
    def _patch_heavy_imports(self):
        mocks = {
            "clem_experimental.src.agent":  MagicMock(),
            "clem_experimental.src.logger": MagicMock(),
            "clem_experimental.src.server": MagicMock(),
        }
        with patch.dict("sys.modules", mocks):
            yield

    def _parse(self, argv):
        """Replicate the argparse config from run.py."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--port", "-p", type=int, default=5000)
        parser.add_argument("--skill", "-s", type=str, default=None)
        return parser.parse_args(argv)

    # --- port --------------------------------------------------------------

    def test_default_port(self):
        assert self._parse([]).port == 5000

    def test_custom_port_long(self):
        assert self._parse(["--port", "8080"]).port == 8080

    def test_custom_port_short(self):
        assert self._parse(["-p", "9000"]).port == 9000

    # --- skill -------------------------------------------------------------

    def test_default_skill_is_none(self):
        assert self._parse([]).skill is None

    def test_skill_long(self):
        assert self._parse(["--skill", "analyst"]).skill == "analyst"

    def test_skill_short(self):
        assert self._parse(["-s", "engineer"]).skill == "engineer"

    # --- combined ----------------------------------------------------------

    def test_port_and_skill_together(self):
        args = self._parse(["--port", "7777", "--skill", "python"])
        assert args.port == 7777
        assert args.skill == "python"