"""
steam.py – Steam quest helpers: registry, API, appmanifest, and quest mode UI.

How Discord really detects Steam games
-------------------------------------
Reverse engineered from the shipped client (Discord 1.0.9259). The Steam
observer lives in ``modules/discord_utils-1/discord_utils/discord_utils.node``
(compiled from ``steam_observer_win.cpp``) and it works like this:

* ``SteamObserver::updateInstalledSkus`` enumerates the subkeys of
  ``HKCU\\SOFTWARE\\Valve\\Steam\\Apps`` and treats every subkey *name* as an
  installed Steam app id.
* ``SteamObserver::DetectSteamGame`` opens ``Software\\Valve\\Steam\\Apps\\<appid>``
  (the format string ``Software\\Valve\\Steam\\Apps\\%d`` is in the binary) and
  reads values such as ``Installed`` / ``RunningAppID`` / ``DefaultDisplayName``.
* The *exe path* decides the distributor: a running process below
  ``<library>/steamapps/common/`` is reported with ``distributor: "steam"``.
  The library list comes from ``<SteamPath>\\config\\libraryfolders.vdf`` plus
  ``HKCU\\SOFTWARE\\Valve\\Steam`` -> ``SteamPath``.
* A process the observer cannot attribute to an installed app is flagged
  ``hidden``, and the renderer drops hidden games before reporting any
  activity - so a fake that is not in the registry is silently ignored.

What is *not* used: the strings ``appmanifest``, ``AppState`` and ``StateFlags``
do not exist anywhere in Discord's binaries, so ``appmanifest_<appid>.acf`` is
never read. Writing one only makes the fake install folder look real (and
teaches the real Steam client about a game you do not own). The registry entry
is the part that matters.
"""

import os
import re
import sys
import time
from typing import Any, TypedDict, cast
from pathlib import Path

from . import config
from .faker import GameFaker
from .ui import (
    Colors, print_color, print_boxed_title,
    loading_animation, ask_confirm,
)
from .net import fetch_json
from .errors import NetworkError

# Windows registry – optional
try:
    import winreg as _winreg
except ImportError:
    _winreg = None

REG_SZ = 1
REG_DWORD = 4
if _winreg is not None:
    REG_SZ = _winreg.REG_SZ
    REG_DWORD = _winreg.REG_DWORD

#: Registry key whose subkeys Discord reads as "installed Steam apps"
STEAM_APPS_KEY = r"Software\Valve\Steam\Apps"
#: Registry key holding the Steam installation path
STEAM_KEY = r"Software\Valve\Steam"


class SteamAppInfo(TypedDict):
    name: str
    installdir: str
    executable: str
    depot_id: str | None


class SteamStoreItem(TypedDict):
    id: int
    name: str


class SteamLaunchEntry(TypedDict, total=False):
    executable: str
    config: dict[str, str]


SteamLaunchMap = dict[str, SteamLaunchEntry]
SteamDataMap = dict[str, Any]

STEAM_ID64_BASE = 76561197960265728


# ── Pure helpers (unit tested) ────────────────────────────────────────────────

def steam_app_key(appid: int | str) -> str:
    """Registry subkey of a single Steam app, as Discord's observer builds it."""
    return f"{STEAM_APPS_KEY}\\{appid}"


def steam_app_values(name: str | None = None) -> dict[str, tuple[int, Any]]:
    """Values Steam itself writes under ``Apps\\<appid>``.

    Mirrors a real entry: an app is listed with ``Installed``/``Updating``/
    ``Running`` flags and, once it has been run at least once, a ``Name``.
    """
    values: dict[str, tuple[int, Any]] = {
        "Installed": (REG_DWORD, 1),
        "Updating": (REG_DWORD, 0),
        "Running": (REG_DWORD, 0),
        "LastPlayed": (REG_DWORD, int(time.time())),
    }
    if name:
        values["Name"] = (REG_SZ, str(name))
    return values


def steam_id64_from_account_id(account_id: int | str) -> str:
    """Convert Steam's 32-bit account id to the 64-bit SteamID."""
    try:
        return str(int(account_id) + STEAM_ID64_BASE)
    except (TypeError, ValueError):
        return "0"


def escape_vdf(value: str) -> str:
    """Escape a value for a VDF/KeyValues1 text file (backslashes and quotes)."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def sanitize_installdir(name: str) -> str:
    """Turn a game name into a folder name Steam would accept."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name)).strip().strip(".")
    return cleaned or "orbshacker"


def steam_library_folders(steam_path: Path) -> list[Path]:
    """Best-effort read of the library folders listed in libraryfolders.vdf."""
    folders: list[Path] = [steam_path]
    vdf = steam_path / "config" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return folders
    for match in re.finditer(r'"path"\s*"([^"]+)"', text):
        raw = match.group(1).replace("\\\\", "\\")
        candidate = Path(raw)
        if candidate.is_dir() and candidate not in folders:
            folders.append(candidate)
    return folders


# ── Registry helpers ──────────────────────────────────────────────────────────

def get_steam_path() -> Path | None:
    """Read Steam installation path from the Windows registry."""
    if sys.platform != 'win32' or _winreg is None:
        return None
    for hive, key in (
        (_winreg.HKEY_CURRENT_USER, STEAM_KEY),
        (_winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        (_winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
    ):
        try:
            with _winreg.OpenKey(hive, key) as handle:
                steam_exe, _ = _winreg.QueryValueEx(handle, "SteamExe")
                candidate = Path(str(steam_exe).replace("/", "\\")).parent
                if candidate.exists():
                    return candidate
        except OSError:
            continue
        try:
            with _winreg.OpenKey(hive, key) as handle:
                for value_name in ("InstallPath", "SteamPath"):
                    value, _ = _winreg.QueryValueEx(handle, value_name)
                    candidate = Path(str(value).replace("/", "\\"))
                    if candidate.exists():
                        return candidate
        except OSError:
            continue
    fallback = Path("C:/Program Files (x86)/Steam")
    return fallback if fallback.exists() else None


def get_steam_user_id() -> str:
    """Read the currently logged-in Steam user ID from registry (SteamID64)."""
    if sys.platform != 'win32' or _winreg is None:
        return "0"
    try:
        with _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, STEAM_KEY + r"\ActiveProcess") as handle:
            value, _ = _winreg.QueryValueEx(handle, "ActiveUser")
        return steam_id64_from_account_id(value)
    except OSError:
        return "0"


def list_installed_steam_apps() -> dict[str, dict[str, Any]]:
    """Return ``{appid: {value: data}}`` for everything under ``Apps``.

    This is exactly the set Discord's steam observer treats as installed.
    """
    if sys.platform != 'win32' or _winreg is None:
        return {}
    apps: dict[str, dict[str, Any]] = {}
    try:
        with _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, STEAM_APPS_KEY) as root:
            subkey_count = _winreg.QueryInfoKey(root)[0]
            for index in range(subkey_count):
                appid = _winreg.EnumKey(root, index)
                entry: dict[str, Any] = {}
                try:
                    with _winreg.OpenKey(root, appid) as app_key:
                        for value_name in ("Installed", "Updating", "Running", "Name"):
                            try:
                                entry[value_name] = _winreg.QueryValueEx(app_key, value_name)[0]
                            except OSError:
                                pass
                except OSError:
                    pass
                apps[appid] = entry
    except OSError:
        return {}
    return apps


def is_steam_app_registered(appid: int | str) -> bool:
    """True when Discord's observer would consider *appid* installed."""
    if sys.platform != 'win32' or _winreg is None:
        return False
    try:
        with _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, steam_app_key(appid)):
            return True
    except OSError:
        return False


def register_steam_app(appid: int | str, name: str | None = None) -> bool:
    """Register an app under ``HKCU\\Software\\Valve\\Steam\\Apps``.

    This is the part Discord actually checks - without it a faked process
    inside ``steamapps/common`` is reported as ``hidden`` and dropped before
    any activity is sent.
    """
    if sys.platform != 'win32' or _winreg is None:
        return False
    try:
        with _winreg.CreateKeyEx(
            _winreg.HKEY_CURRENT_USER, steam_app_key(appid), 0, _winreg.KEY_WRITE
        ) as handle:
            for value_name, (value_type, value) in steam_app_values(name).items():
                _winreg.SetValueEx(handle, value_name, 0, value_type, value)
    except OSError as exc:
        print_color(f"[!] Could not register Steam app {appid}: {exc}", Colors.YELLOW)
        return False
    return True


def unregister_steam_app(appid: int | str) -> bool:
    """Remove an app key created by :func:`register_steam_app`."""
    if sys.platform != 'win32' or _winreg is None:
        return False
    try:
        _winreg.DeleteKey(_winreg.HKEY_CURRENT_USER, steam_app_key(appid))
        return True
    except OSError:
        return False


# ── API helpers ───────────────────────────────────────────────────────────────

def _pick_windows_exe(launch: SteamLaunchMap) -> str | None:
    """Return the first Windows .exe found in a SteamCMD launch dict."""
    for key in sorted(launch.keys()):
        entry = launch[key]
        oslist = entry.get("config", {}).get("oslist", "windows")
        if "windows" in oslist or oslist == "":
            exe = entry.get("executable", "")
            if exe.endswith(".exe"):
                return exe.replace("\\", "/")
    return None


def fetch_steam_app_info(appid: int) -> SteamAppInfo | None:
    """Fetch app info from SteamCMD API. Returns dict or None on failure."""
    url = f"{config.STEAMCMD_API_URL}/{appid}"
    try:
        loading_animation(f"Fetching Steam app info for {appid}", 1.2)
        data = cast(SteamDataMap, fetch_json(url))

        data_root = cast(dict[str, SteamDataMap], data.get("data", {}))
        app_data = data_root.get(str(appid), {})
        common_cfg = cast(dict[str, str], app_data.get("common", {}))
        app_cfg = cast(dict[str, Any], app_data.get("config", {}))

        name = common_cfg.get("name", f"App {appid}")
        installdir = str(app_cfg.get("installdir") or sanitize_installdir(name))
        launch_map = cast(SteamLaunchMap, app_cfg.get("launch", {}))
        executable = _pick_windows_exe(launch_map)

        if not executable:
            executable = installdir.split("/")[-1] + ".exe"

        depots = cast(dict[str, Any], app_data.get("depots", {}))
        depot_id = next((key for key in depots.keys() if key.isdigit()), None)
        return {"name": name, "installdir": installdir, "executable": executable, "depot_id": depot_id}

    except NetworkError as e:
        print_color(f"[!] SteamCMD API error: {e}", Colors.YELLOW)
        return None


def search_steam_games(query: str) -> list[SteamStoreItem]:
    """Search Steam store. Returns list of {id, name} dicts."""
    try:
        loading_animation(f"Searching Steam for '{query}'", 1.0)
        data = cast(dict[str, Any], fetch_json(
            config.STEAM_STORE_SEARCH_URL,
            params={"term": query, "l": "english", "cc": "US"},
        ))
        return cast(list[SteamStoreItem], data.get("items", []))
    except NetworkError as e:
        print_color(f"[!] Steam search error: {e}", Colors.YELLOW)
        return []


# ── Appmanifest generation (cosmetic - Discord never reads it) ─────────────────

_ACF_TEMPLATE = '''"AppState"
{{
\t"appid"\t\t"{appid}"
\t"Universe"\t\t"1"
\t"LauncherPath"\t\t"{launcher}"
\t"name"\t\t"{name}"
\t"StateFlags"\t\t"{state_flags}"
\t"installdir"\t\t"{installdir}"
\t"LastUpdated"\t\t"{last_updated}"
\t"LastPlayed"\t\t"{last_played}"
\t"SizeOnDisk"\t\t"{size_on_disk}"
\t"StagingSize"\t\t"0"
\t"buildid"\t\t"{buildid}"
\t"LastOwner"\t\t"{owner}"
\t"DownloadType"\t\t"0"
\t"UpdateResult"\t\t"0"
\t"BytesToDownload"\t\t"0"
\t"BytesDownloaded"\t\t"0"
\t"BytesToStage"\t\t"0"
\t"BytesStaged"\t\t"0"
\t"TargetBuildID"\t\t"{buildid}"
\t"AutoUpdateBehavior"\t\t"0"
\t"AllowOtherDownloadsWhileRunning"\t\t"0"
\t"ScheduledAutoUpdate"\t\t"0"
\t"InstalledDepots"
\t{{
{installed_depots}\t}}
\t"UserConfig"
\t{{
\t\t"language"\t\t"english"
\t}}
\t"MountedConfig"
\t{{
\t\t"language"\t\t"english"
\t}}
}}
'''

_DEPOT_TEMPLATE = '''\t\t"{depot_id}"
\t\t{{
\t\t\t"manifest"\t\t"{manifest_id}"
\t\t\t"size"\t\t"{size}"
\t\t}}


'''


def render_appmanifest(
    appid: int,
    name: str,
    installdir: str,
    steam_path: Path,
    depot_id: str | None = None,
    owner: str | None = None,
    build_id: int | None = None,
) -> str:
    """Render a realistic, fully-installed ``appmanifest_<appid>.acf``.

    Discord does not read this file (there is no ``appmanifest`` string in its
    binaries) - it only makes the fake install folder look like a real Steam
    install. ``StateFlags 4`` means "fully installed".
    """
    now = int(time.time())
    build = build_id or 10000000 + (int(appid) % 90000000)
    installed_depots = ""
    if depot_id:
        installed_depots = _DEPOT_TEMPLATE.format(
            depot_id=escape_vdf(str(depot_id)),
            manifest_id=str(1700000000000000000 + int(appid)),
            size=str(2 * 1024 * 1024 * 1024),
        )
    return _ACF_TEMPLATE.format(
        appid=int(appid),
        launcher=escape_vdf(str(steam_path / "steam.exe")),
        name=escape_vdf(name),
        state_flags=4,
        installdir=escape_vdf(installdir),
        last_updated=now,
        last_played=now,
        size_on_disk=2 * 1024 * 1024 * 1024,
        buildid=build,
        owner=escape_vdf(owner or get_steam_user_id()),
        installed_depots=installed_depots,
    )


def generate_appmanifest(
    appid: int,
    name: str,
    installdir: str,
    steam_path: Path,
    depot_id: str | None = None,
) -> Path | None:
    """Write ``steamapps/appmanifest_<appid>.acf`` next to the faked install."""
    acf_path = steam_path / "steamapps" / f"appmanifest_{appid}.acf"
    try:
        acf_path.parent.mkdir(parents=True, exist_ok=True)
        acf_path.write_text(
            render_appmanifest(appid, name, installdir, steam_path, depot_id=depot_id),
            encoding="utf-8",
        )
        print_color(f"[OK] Created appmanifest: {acf_path}", Colors.GRAY)
        return acf_path
    except OSError as e:
        print_color(f"[ERROR] Failed to write appmanifest: {e}", Colors.RED, bold=True)
        return None


# ── Interactive UI for Steam Quest Mode ───────────────────────────────────────

def _resolve_steam_path() -> Path | None:
    """Auto-detect or prompt for Steam path."""
    steam_path = get_steam_path()
    if steam_path and steam_path.exists():
        return steam_path
    print_color("[!] Could not locate Steam automatically.", Colors.YELLOW)
    manual = input(
        f"{Colors.BOLD}Enter Steam path manually{Colors.RESET}"
        " (e.g. C:/Program Files (x86)/Steam): "
    ).strip()
    if not manual:
        print_color("[!] No Steam path provided. Aborting.", Colors.RED)
        return None
    return Path(manual)


def _pick_steam_game(query: str) -> SteamStoreItem | None:
    """Search Steam and let the user choose a game."""
    results = search_steam_games(query)
    if not results:
        print_color(f"\n[ERROR] No results found for '{query}'", Colors.RED)
        print_color("[!] Try a different search term", Colors.YELLOW)
        time.sleep(config.SLEEP_LONG)
        return None

    print(f"\n{Colors.BOLD}{Colors.GREEN}Found {len(results)} result(s):{Colors.RESET}\n")
    print(f"{Colors.GRAY}{'─' * 60}{Colors.RESET}")
    for idx, game in enumerate(results, 1):
        print(f"  {Colors.BOLD}{Colors.CYAN}{idx:2d}.{Colors.RESET} {Colors.WHITE}{game['name']}{Colors.RESET}  {Colors.GRAY}(AppID: {game['id']}){Colors.RESET}")
        if idx < len(results):
            print(f"{Colors.GRAY}{'─' * 60}{Colors.RESET}")
    print()

    raw = input(f"{Colors.BOLD}Select [1-{len(results)}]{Colors.RESET} (or 'back'): ").strip()
    if raw.lower() in ('back', 'b', ''):
        return None
    try:
        idx = int(raw)
        if not 1 <= idx <= len(results):
            raise ValueError
    except ValueError:
        print_color("[ERROR] Invalid selection.", Colors.RED)
        time.sleep(config.SLEEP_SHORT)
        return None
    return results[idx - 1]


def _prompt_app_info_manually(appid: int) -> SteamAppInfo:
    """Fallback: ask user to type Steam app info."""
    print_color("[!] Could not fetch app info automatically.", Colors.YELLOW)
    print_color("[*] Enter details manually:", Colors.CYAN)
    return {
        "name":       input(f"  {Colors.BOLD}Game name{Colors.RESET}: ").strip() or f"App {appid}",
        "installdir": input(f"  {Colors.BOLD}Install dir{Colors.RESET} (folder in steamapps/common): ").strip() or f"App{appid}",
        "executable": input(f"  {Colors.BOLD}Executable{Colors.RESET} (e.g. Bin/Game.exe): ").strip() or "Game.exe",
        "depot_id":   None,
    }


def _print_how_it_works(appid: int) -> None:
    print(f"\n{Colors.GRAY}  How Discord sees this:{Colors.RESET}")
    print(f"  {Colors.GRAY}1. Registry  HKCU\\{steam_app_key(appid)} = installed{Colors.RESET}")
    print(f"  {Colors.GRAY}2. Exe path  <steam>\\steamapps\\common\\<installdir>\\ -> distributor=steam{Colors.RESET}")
    print(f"  {Colors.GRAY}3. Name      must match Discord's game name so the client can map it{Colors.RESET}")
    print(f"  {Colors.YELLOW}[!] Keep the Steam client CLOSED, it rewrites the registry and manifests.{Colors.RESET}")
    print(f"  {Colors.YELLOW}[!] Restart Discord after setup if the game does not show up.{Colors.RESET}")


def steam_quest_mode(faker: GameFaker, preset: dict[str, Any] | None = None) -> None:
    """Steam Quest Mode – registers a fake Steam install and launches it.

    *preset* may carry ``appid`` and ``name`` taken from Discord's own
    database, which is the authoritative app id for a game.
    """
    print_boxed_title("STEAM QUEST MODE", width=55, color=Colors.CYAN)
    print_color("[*] Registers the app in the Steam registry, then fakes its install folder", Colors.CYAN)
    print_color("[*] Needed for games Discord lists without a process name (Marathon, EA FC 27…)", Colors.GRAY)
    print_color("[*] Demos and DLCs are separate app ids - pick the right one!", Colors.YELLOW)
    print()

    steam_path = _resolve_steam_path()
    if not steam_path:
        return
    print_color(f"[OK] Steam found at: {steam_path}", Colors.GREEN)

    if preset and preset.get("appid"):
        appid = int(preset["appid"])
        game_name = str(preset.get("name") or f"App {appid}")
        print_color(f"\n[OK] Using Discord's app id: {appid} ({game_name})", Colors.GREEN, bold=True)
    else:
        query = input(f"\n{Colors.BOLD}Search game{Colors.RESET} (or 'back'): ").strip()
        if query.lower() in ('back', 'b', ''):
            return

        game = _pick_steam_game(query)
        if not game:
            return

        appid = int(game["id"])
        game_name = str(game["name"])
        print_color(f"\n[OK] Selected: {game_name} (AppID: {appid})", Colors.GREEN, bold=True)

    info = fetch_steam_app_info(appid) or _prompt_app_info_manually(appid)
    discord_name = game_name or info['name']
    installdir = sanitize_installdir(info['installdir'])

    print(f"\n{Colors.BOLD}Detected info:{Colors.RESET}")
    print(f"  App id:      {Colors.CYAN}{appid}{Colors.RESET}")
    print(f"  Steam name:  {Colors.CYAN}{info['name']}{Colors.RESET}")
    print(f"  Install dir: {Colors.CYAN}{installdir}{Colors.RESET}")
    print(f"  Executable:  {Colors.CYAN}{info['executable']}{Colors.RESET}")
    print(f"  {Colors.GRAY}The window title / registry Name uses Discord's name: {discord_name!r}{Colors.RESET}")

    override = input(f"\n{Colors.BOLD}Override executable path?{Colors.RESET} [leave empty to keep]: ").strip()
    if override:
        info['executable'] = override.replace("\\", "/")

    exe_full_path = f"{installdir}/{info['executable']}"
    fake_exe_path = steam_path / "steamapps" / "common" / exe_full_path.replace("/", os.sep)
    registry_key = steam_app_key(appid)

    print(f"\n{Colors.BOLD}Summary:{Colors.RESET}")
    print(f"  Registry key: {Colors.GRAY}{registry_key}{Colors.RESET}")
    print(f"  Fake exe:     {Colors.GRAY}{fake_exe_path}{Colors.RESET}")
    if config.STEAM_WRITE_APPMANIFEST:
        print(f"  Appmanifest:  {Colors.GRAY}{steam_path / 'steamapps' / f'appmanifest_{appid}.acf'} (cosmetic){Colors.RESET}")

    if not ask_confirm():
        print_color("\n[!] Operation cancelled.", Colors.YELLOW)
        time.sleep(config.SLEEP_SHORT)
        return

    # 1. Register the app so Discord's steam observer treats it as installed
    already_registered = is_steam_app_registered(appid)
    if already_registered:
        print_color(f"[OK] App {appid} is already registered in the Steam registry", Colors.GRAY)
    elif register_steam_app(appid, name=discord_name):
        print_color(f"[OK] Registered {registry_key} (Installed=1)", Colors.GREEN, bold=True)
        faker.register_created_registry_key(appid)
    else:
        print_color("[!] Could not write the registry - detection will likely fail", Colors.RED, bold=True)

    # 2. Optional cosmetic appmanifest
    acf: Path | None = None
    if config.STEAM_WRITE_APPMANIFEST:
        acf = generate_appmanifest(appid, discord_name, installdir, steam_path, depot_id=info.get('depot_id'))
        if acf:
            faker.register_created_file(acf)

    # 3. The faked executable, inside the library folder Discord scans
    try:
        loading_animation(f"Creating {info['executable'].split('/')[-1]}", 0.8)
        config.STEAM_MANIFEST_PATH = acf
        faker.copy_exe_to(fake_exe_path, title=discord_name)
        print_color(f"[OK] Created: {fake_exe_path}", Colors.GREEN, bold=True)
    except Exception as e:
        print_color(f"[ERROR] Failed to copy exe: {e}", Colors.RED, bold=True)
        time.sleep(config.SLEEP_SHORT)
        return
    finally:
        if hasattr(config, "STEAM_MANIFEST_PATH"):
            delattr(config, "STEAM_MANIFEST_PATH")

    print()
    faker.launch_executable(fake_exe_path)
    print_color("\n[OK] Steam Quest setup complete!", Colors.GREEN, bold=True)
    print_color("[!] Discord MUST be running for detection to work.", Colors.YELLOW)
    print_color("[*] Keep the process running until the quest is done.", Colors.CYAN)
    _print_how_it_works(appid)
    input(f"\n{Colors.GRAY}Press Enter to continue...{Colors.RESET}")
