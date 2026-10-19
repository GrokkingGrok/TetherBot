# SPDX-License-Identifier: GPL-2.0-or-later
"""Installer scripts stay idempotent and shellcheck-clean. No secrets are read."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    ROOT / "scripts" / "install.sh",
    ROOT / "scripts" / "uninstall.sh",
    ROOT / "scripts" / "install-extension.sh",
    ROOT / "scripts" / "launchers" / "tetherbot",
    ROOT / "scripts" / "launchers" / "tetherbotctl",
    ROOT / "scripts" / "launchers" / "git-credential-tetherbot",
    ROOT / "scripts" / "launchers" / "tetherbot-window",
]


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOME/systemctl.log\"\nexit 0\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def test_scripts_pass_bash_n():
    for script in SCRIPTS:
        subprocess.run(["bash", "-n", str(script)], check=True, timeout=30)


def test_scripts_are_shellcheck_clean():
    shellcheck = subprocess.run(
        ["sh", "-c", "command -v shellcheck"],
        capture_output=True,
        text=True,
    )
    if shellcheck.returncode != 0:
        pytest.skip("shellcheck is not installed")
    subprocess.run(
        ["shellcheck", "-x", *[str(script) for script in SCRIPTS]],
        check=True,
        timeout=60,
    )


def test_install_and_uninstall_are_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = _env(home)
    install = ROOT / "scripts" / "install.sh"
    uninstall = ROOT / "scripts" / "uninstall.sh"
    subprocess.run(["bash", str(install)], check=True, env=env, timeout=60)
    subprocess.run(["bash", str(install)], check=True, env=env, timeout=60)
    app = home / ".local" / "share" / "tetherbot" / "app"
    assert (app / "tetherbot" / "__init__.py").is_file()
    assert (app / "tetherbot" / "io.github.grokkinggrok.TetherBot1.xml").is_file()
    assert not (app / "SCAFFOLD").exists()
    for name in ("tetherbot", "tetherbotctl", "git-credential-tetherbot", "tetherbot-window"):
        path = home / ".local" / "bin" / name
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) & 0o111
    unit = (home / ".config" / "systemd" / "user" / "tetherbot.service").read_text(encoding="utf-8")
    assert "/bin/false" not in unit
    assert "%h/.local/bin/tetherbot" in unit
    assert "BusName=io.github.grokkinggrok.TetherBot1" in unit
    assert "PartOf=graphical-session.target" in unit
    assert "WantedBy=graphical-session.target" in unit
    assert "WantedBy=default.target" not in unit
    dbus_path = home / ".local" / "share" / "dbus-1" / "services"
    dbus = (dbus_path / "io.github.grokkinggrok.TetherBot1.service").read_text(encoding="utf-8")
    assert "SystemdService=tetherbot.service" in dbus
    assert f"Exec={home / '.local' / 'bin' / 'tetherbot'}" in dbus
    assert "@TETHERBOT_LAUNCHER@" not in dbus
    window_dbus = (dbus_path / "io.github.grokkinggrok.TetherBot.service").read_text(
        encoding="utf-8"
    )
    window_bin = home / ".local" / "bin" / "tetherbot-window"
    assert "Name=io.github.grokkinggrok.TetherBot" in window_dbus
    assert f"Exec={window_bin}" in window_dbus
    assert "@TETHERBOT_WINDOW@" not in window_dbus
    desktop = (
        home / ".local" / "share" / "applications" / "io.github.grokkinggrok.TetherBot.desktop"
    ).read_text(encoding="utf-8")
    assert "DBusActivatable=true" in desktop
    assert "Not affiliated with xAI." in desktop
    assert f"Exec={window_bin}" in desktop
    assert "view-list-symbolic" in desktop
    config = home / ".config" / "tetherbot" / "config.toml"
    assert config.is_file()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    log = (home / "systemctl.log").read_text(encoding="utf-8")
    assert "daemon-reload" in log
    assert "enable --now" not in log

    env_py = env.copy()
    env_py["PYTHONPATH"] = str(app)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import tetherbot, tetherbot.credential, tetherbot.ctl, tetherbot.sweep",
        ],
        check=True,
        env=env_py,
        timeout=30,
    )

    refused = subprocess.run(
        ["bash", str(install), "--nope"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert refused.returncode == 2

    subprocess.run(["bash", str(install), "--enable"], check=True, env=env, timeout=60)
    log = (home / "systemctl.log").read_text(encoding="utf-8")
    assert "enable --now tetherbot.service" in log

    subprocess.run(["bash", str(uninstall)], check=True, env=env, timeout=60)
    assert not (home / ".local" / "bin" / "tetherbot").exists()
    assert not (home / ".local" / "bin" / "tetherbot-window").exists()
    assert not (dbus_path / "io.github.grokkinggrok.TetherBot.service").exists()
    assert not (
        home / ".local" / "share" / "applications" / "io.github.grokkinggrok.TetherBot.desktop"
    ).exists()
    assert not app.exists()
    assert config.is_file()
    subprocess.run(["bash", str(uninstall), "--purge", "--yes"], check=True, env=env, timeout=60)
    assert not config.exists()
    assert not (home / ".local" / "share" / "tetherbot").exists()
    subprocess.run(["bash", str(uninstall), "--purge", "--yes"], check=True, env=env, timeout=60)


def test_install_moves_an_old_default_target_enablement(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = _env(home)
    wants = home / ".config" / "systemd" / "user" / "default.target.wants"
    wants.mkdir(parents=True)
    link = wants / "tetherbot.service"
    link.symlink_to("../tetherbot.service")
    subprocess.run(["bash", str(ROOT / "scripts" / "install.sh")], check=True, env=env, timeout=60)
    assert not link.exists()
    log = (home / "systemctl.log").read_text(encoding="utf-8")
    assert "--user enable tetherbot.service" in log
    assert "enable --now" not in log
    unit = (home / ".config" / "systemd" / "user" / "tetherbot.service").read_text(encoding="utf-8")
    assert "WantedBy=graphical-session.target" in unit


def test_uninstall_removes_both_enablement_links(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = _env(home)
    user = home / ".config" / "systemd" / "user"
    for name in ("default.target.wants", "graphical-session.target.wants"):
        directory = user / name
        directory.mkdir(parents=True)
        (directory / "tetherbot.service").symlink_to("../tetherbot.service")
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "uninstall.sh")],
        check=True,
        env=env,
        timeout=60,
    )
    assert not (user / "default.target.wants" / "tetherbot.service").exists()
    assert not (user / "graphical-session.target.wants" / "tetherbot.service").exists()


def test_extension_install_copies_the_uuid(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = _env(home)
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "install-extension.sh")],
        check=True,
        env=env,
        timeout=30,
    )
    dest = (
        home
        / ".local"
        / "share"
        / "gnome-shell"
        / "extensions"
        / "tetherbot@grokkinggrok.github.io"
    )
    assert (dest / "metadata.json").is_file()
    assert (dest / "extension.js").is_file()
    assert not (dest / "test_view.js").exists()
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "uninstall.sh")],
        check=True,
        env=env,
        timeout=30,
    )
    assert not dest.exists()
