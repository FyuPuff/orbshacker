"""Tests for steam.py – pure functions only (no network calls)."""

from pathlib import Path

import pytest

from orbshacker.steam import (
    REG_DWORD,
    REG_SZ,
    _pick_windows_exe,
    escape_vdf,
    render_appmanifest,
    sanitize_installdir,
    steam_app_key,
    steam_app_values,
    steam_id64_from_account_id,
    steam_library_folders,
)


class TestPickWindowsExe:
    def test_finds_first_windows_exe(self):
        launch = {
            "0": {
                "executable": "game.exe",
                "config": {"oslist": "windows"},
            },
            "1": {
                "executable": "game_server.exe",
                "config": {"oslist": "windows"},
            },
        }
        assert _pick_windows_exe(launch) == "game.exe"

    def test_skips_non_windows(self):
        launch = {
            "0": {
                "executable": "game.app",
                "config": {"oslist": "macos"},
            },
            "1": {
                "executable": "game.exe",
                "config": {"oslist": "windows"},
            },
        }
        assert _pick_windows_exe(launch) == "game.exe"

    def test_skips_non_exe(self):
        launch = {
            "0": {
                "executable": "game.sh",
                "config": {"oslist": "windows"},
            },
        }
        assert _pick_windows_exe(launch) is None

    def test_empty_launch(self):
        assert _pick_windows_exe({}) is None

    def test_normalises_backslashes(self):
        launch = {
            "0": {
                "executable": "Bin\\Win64\\game.exe",
                "config": {"oslist": "windows"},
            },
        }
        assert _pick_windows_exe(launch) == "Bin/Win64/game.exe"

    def test_empty_oslist_counts_as_windows(self):
        launch = {
            "0": {
                "executable": "game.exe",
                "config": {"oslist": ""},
            },
        }
        assert _pick_windows_exe(launch) == "game.exe"


# ── Registry shape (what Discord's SteamObserver actually reads) ──────────────

def test_steam_app_key_matches_native_format_string():
    # SteamObserver::DetectSteamGame builds "Software\Valve\Steam\Apps\%d"
    assert steam_app_key(4080220) == r"Software\Valve\Steam\Apps\4080220"


def test_steam_app_values_mirror_a_real_entry():
    values = steam_app_values("EA Sports FC 27")
    assert values["Installed"] == (REG_DWORD, 1)
    assert values["Updating"] == (REG_DWORD, 0)
    assert values["Running"] == (REG_DWORD, 0)
    assert values["Name"] == (REG_SZ, "EA Sports FC 27")
    assert "LastPlayed" in values


def test_steam_app_values_without_name():
    values = steam_app_values()
    assert "Name" not in values
    assert values["Installed"][1] == 1


def test_steam_id64_conversion():
    # 1263306433 is the ActiveUser value on the reference machine, and
    # 76561199223572161 is the LastOwner its real manifests carry
    assert steam_id64_from_account_id(1263306433) == "76561199223572161"
    assert steam_id64_from_account_id("bogus") == "0"


# ── VDF / path helpers ────────────────────────────────────────────────────────

def test_escape_vdf_doubles_backslashes():
    assert escape_vdf(r"C:\Program Files (x86)\Steam\steam.exe") == \
        r"C:\\Program Files (x86)\\Steam\\steam.exe"
    assert escape_vdf('say "hi"') == 'say \\"hi\\"'


def test_sanitize_installdir():
    assert sanitize_installdir("EA SPORTS FC 27") == "EA SPORTS FC 27"
    assert sanitize_installdir('Bad/Name:With*Junk') == "BadNameWithJunk"
    assert sanitize_installdir("   ") == "orbshacker"


def test_steam_library_folders_reads_vdf(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "config").mkdir(parents=True)
    extra = tmp_path / "SteamLibrary"
    extra.mkdir()
    (steam / "config" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
        + str(steam).replace("\\", "\\\\")
        + '"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"'
        + str(extra).replace("\\", "\\\\")
        + '"\n\t}\n}\n',
        encoding="utf-8",
    )
    folders = steam_library_folders(steam)
    assert folders[0] == steam
    assert extra in folders


def test_steam_library_folders_without_vdf(tmp_path):
    steam = tmp_path / "Steam"
    steam.mkdir()
    assert steam_library_folders(steam) == [steam]


# ── Appmanifest (cosmetic) ────────────────────────────────────────────────────

def test_render_appmanifest_looks_installed(tmp_path):
    steam = tmp_path / "Steam"
    text = render_appmanifest(
        4080220, "EA Sports FC 27", "EA SPORTS FC 27", steam, depot_id="228989"
    )
    assert '"AppState"' in text
    assert '"appid"\t\t"4080220"' in text
    # fully installed, not "downloading"
    assert '"StateFlags"\t\t"4"' in text
    assert "1026" not in text
    # VDF-escaped launcher path
    assert str(steam / "steam.exe").replace("\\", "\\\\") in text
    assert '"installdir"\t\t"EA SPORTS FC 27"' in text
    assert '"228989"' in text
    assert '"language"\t\t"english"' in text


def test_render_appmanifest_without_depot(tmp_path):
    text = render_appmanifest(5124200, "Screen Stocks Demo", "Screen Stocks Demo", tmp_path / "Steam")
    assert '"InstalledDepots"' in text
    assert '"manifest"' not in text


def test_render_appmanifest_escapes_quotes(tmp_path):
    text = render_appmanifest(1, 'Weird "Name"', "Weird", tmp_path)
    assert 'Weird \\"Name\\"' in text
