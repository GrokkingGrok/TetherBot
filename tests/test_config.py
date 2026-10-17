# SPDX-License-Identifier: GPL-2.0-or-later
"""Config loader: example file, schema gate, and secret rejection."""

from pathlib import Path

import pytest

from tetherbot.config import ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "data" / "config.example.toml"


def test_example_config_is_opt_in():
    config = load_config(EXAMPLE)
    assert config.schema == "tetherbot/1"
    assert config.mode == "webhook-only"
    assert config.adapters["webhook-sender"].enabled is False
    assert config.adapters["github-poller"].enabled is False
    assert config.adapters["official"].enabled is False
    assert config.sinks["legacy-todo"].enabled is False
    assert config.queue.coalesce_seconds == 20
    assert config.queue.daily_cap == 30
    assert config.bots == {}


def test_unknown_schema_fails_closed(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('schema = "tetherbot/2"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="unsupported schema tetherbot/2"):
        load_config(path)


def test_secret_values_and_forbidden_keys_are_rejected(tmp_path: Path):
    path = tmp_path / "config.toml"
    secret = "ghp_abcdefghijklmnopqrstuvwxyz"
    path.write_text(
        f'schema = "tetherbot/1"\nnote = "{secret}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="looks like a secret") as caught:
        load_config(path)
    assert secret not in str(caught.value)

    path.write_text('schema = "tetherbot/1"\ntoken = "placeholder"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="token is not allowed"):
        load_config(path)


def test_credential_in_remote_url_is_rejected(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                'schema = "tetherbot/1"',
                "[adapters.github-poller]",
                "enabled = false",
                'remote = "https://user:secret@github.com/OWNER/tetherbot-data.git"',
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="without credentials"):
        load_config(path)
