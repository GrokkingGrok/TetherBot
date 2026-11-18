"""Inline clip editors in the panel menu: the node checks for clip_inline.js."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_inline_editor_logic():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    subprocess.run(
        [node, "extension/clip_inline_checks.js"],
        check=True,
        cwd=ROOT,
        timeout=30,
    )
