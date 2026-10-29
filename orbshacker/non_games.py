"""
non_games.py – Discord non-games mode (browsers and other apps).

Discord keeps these in a separate list from games:

    https://cdn.discordapp.com/detectables/non-games.json

They are detected by process name exactly like games, but the games
database does not contain them (Firefox is there with an empty
``executables`` list), so process-name spoofing needs its own mode.
New entries added by Discord show up here automatically.
"""

from typing import Any, TypedDict

from . import config
from .faker import GameFaker
from .ui import (
    Colors, print_color, print_boxed_title,
    loading_animation, ask_confirm,
)
from .net import fetch_json
from .errors import NetworkError


class NonGameExecutable(TypedDict, total=False):
    os: str
    name: str
    arguments: str
    is_launcher: bool


class NonGameRecord(TypedDict, total=False):
    id: str
    name: str
    aliases: list[str]
    executables: list[NonGameExecutable]
    hook: bool


class ExeChoice(TypedDict):
    """A runnable executable from a non-game entry."""

    path: str        # relative path, e.g. "opera gx/opera.exe"
    exe: str         # process name, e.g. "opera.exe"
    arguments: str   # required command line arguments, if any


def _safe_relative_path(name: str) -> str | None:
    """Normalise an executable entry and reject paths escaping the fake dir."""
    name = name.lstrip(">").replace("\\", "/").strip()
    if not name:
        return None
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if ":" in parts[0]:  # absolute path or drive letter
        return None
    return "/".join(parts)


def get_win32_executables(entry: NonGameRecord) -> list[ExeChoice]:
    """Every Windows executable Discord would accept for this entry."""
    result: list[ExeChoice] = []
    seen: set[str] = set()
    for exe in entry.get("executables", []) or []:
        if exe.get("os") != "win32":
            continue
        rel_path = _safe_relative_path(exe.get("name", ""))
        if not rel_path or not rel_path.lower().endswith(".exe"):
            continue
        if rel_path in seen:
            continue
        seen.add(rel_path)
        result.append({
            "path": rel_path,
            "exe": rel_path.split("/")[-1],
            "arguments": str(exe.get("arguments") or "").strip(),
        })
    return result


def load_non_games() -> list[NonGameRecord]:
    """Fetch Discord's non-games list and keep entries we can fake."""
    print_color("\n[*] Loading Discord non-games list...", Colors.YELLOW)
    loading_animation("Connecting to Discord CDN", 0.8)
    data = fetch_json(
        config.NON_GAMES_URL,
        headers=config.DISCORD_HEADERS,
        timeout=config.REQUEST_TIMEOUT_LONG,
    )
    if not isinstance(data, list):
        raise NetworkError("Discord returned an unexpected non-games list.")

    entries: list[NonGameRecord] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if not entry.get("name") or not get_win32_executables(entry):
            continue
        entries.append(entry)
    return entries


def _print_entries(entries: list[NonGameRecord]) -> None:
    print(f"{Colors.GRAY}{'-' * 75}{Colors.RESET}")
    for idx, entry in enumerate(entries, 1):
        names = ", ".join(exe["exe"] for exe in get_win32_executables(entry))
        print(
            f"{Colors.BOLD}{Colors.CYAN}{idx:2d}.{Colors.RESET} "
            f"{Colors.WHITE}{entry.get('name', 'Unknown')}{Colors.RESET}"
        )
        print(f"    {Colors.GRAY}Process: {names}{Colors.RESET}")
    print(f"{Colors.GRAY}{'-' * 75}{Colors.RESET}\n")


def _pick_entry(entries: list[NonGameRecord]) -> NonGameRecord | None:
    """Pick by number, or search by name / alias."""
    while True:
        raw = input(
            f"{Colors.BOLD}Select{Colors.RESET} [1-{len(entries)}], "
            f"search by name, or 'back': "
        ).strip()
        if raw.lower() in ('back', 'b', ''):
            return None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(entries):
                return entries[idx - 1]
            print_color("\n[ERROR] Enter a valid number", Colors.RED)
            continue

        query = raw.lower()
        matches = [
            entry for entry in entries
            if query in entry.get("name", "").lower()
            or any(query in alias.lower() for alias in entry.get("aliases", []))
        ]
        if not matches:
            print_color(f"\n[ERROR] No non-game found for '{raw}'", Colors.RED)
            continue
        if len(matches) == 1:
            return matches[0]
        _print_entries(matches)
        entries = matches


def _pick_executable(entry: NonGameRecord, choices: list[ExeChoice]) -> ExeChoice | None:
    """Pick one of the executables Discord lists for this entry."""
    if len(choices) == 1:
        return choices[0]

    print(f"\n{Colors.BOLD}This app has {len(choices)} process names:{Colors.RESET}\n")
    for idx, choice in enumerate(choices, 1):
        note = ""
        if choice["arguments"]:
            note = f"  {Colors.YELLOW}(needs arguments: {choice['arguments']}){Colors.RESET}"
        print(
            f"  {Colors.BOLD}{Colors.CYAN}{idx}.{Colors.RESET} "
            f"{Colors.WHITE}{choice['exe']}{Colors.RESET} "
            f"{Colors.GRAY}{choice['path']}{Colors.RESET}{note}"
        )
    print()
    while True:
        raw = input(
            f"{Colors.BOLD}Select executable{Colors.RESET} "
            f"[1-{len(choices)}] (default 1): "
        ).strip()
        if raw.lower() in ('back', 'b'):
            return None
        if raw == '':
            return choices[0]
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        print_color("\n[ERROR] Enter a valid number", Colors.RED)


def _manual_fallback(faker: GameFaker) -> None:
    """Used when the non-games list cannot be downloaded."""
    print_color("\n[!] Could not load Discord's non-games list.", Colors.YELLOW)
    print_color("[*] You can still type the process name manually.", Colors.CYAN)
    exe_name = input(f"{Colors.BOLD}Executable name{Colors.RESET} (or 'back'): ").strip()
    if not exe_name or exe_name.lower() in ('back', 'b'):
        return
    title = input(
        f"{Colors.BOLD}Window title{Colors.RESET} "
        f"(e.g. Firefox, leave empty to use the exe name): "
    ).strip() or None
    result = faker.create_fake_game(exe_name, title=title)
    if result:
        print()
        faker.launch_executable(result)
        print_color("\n[OK] Setup complete!", Colors.GREEN, bold=True)
        print_color("[!] Discord MUST be running for detection to work", Colors.YELLOW)
    input(f"\n{Colors.GRAY}Press Enter to continue...{Colors.RESET}")


def non_games_mode(faker: GameFaker) -> None:
    """Non-Games mode – spoof browsers and other apps Discord tracks."""
    print_boxed_title("NON-GAMES MODE", width=55, color=Colors.CYAN)
    print_color("[*] For Firefox, Chrome, Opera GX and other non-game apps", Colors.CYAN)
    print_color("[*] Discord detects these by process name, separately from games", Colors.GRAY)
    print_color("[*] The list below is live from Discord's CDN", Colors.GRAY)

    try:
        entries = load_non_games()
    except NetworkError as exc:
        print_color(f"[!] {exc}", Colors.YELLOW)
        _manual_fallback(faker)
        return

    print_color(
        f"[OK] Loaded {len(entries)} spoofable non-game(s)",
        Colors.GREEN, bold=True,
    )
    _print_entries(entries)

    while True:
        entry = _pick_entry(entries)
        if not entry:
            return

        choices = get_win32_executables(entry)
        choice = _pick_executable(entry, choices)
        if not choice:
            continue

        target_path = faker.chosen_path / config.FAKE_EXE_DIR / choice["path"]
        print(f"\n{Colors.BOLD}App Information:{Colors.RESET}")
        print(f"  Name:        {Colors.CYAN}{entry.get('name')}{Colors.RESET}")
        print(f"  ID:          {Colors.GRAY}{entry.get('id', 'N/A')}{Colors.RESET}")
        print(f"  Process:     {Colors.GREEN}{choice['exe']}{Colors.RESET}")
        if choice["arguments"]:
            print(f"  Arguments:   {Colors.YELLOW}{choice['arguments']}{Colors.RESET}")
        print(f"  Path:        {Colors.GRAY}{target_path}{Colors.RESET}")

        if not ask_confirm():
            print_color("\n[!] Operation cancelled", Colors.YELLOW)
            continue

        result = faker.create_fake_game(choice["path"], title=entry.get("name"))
        if result:
            print()
            faker.launch_executable(result, arguments=choice["arguments"] or None)
            print_color(
                "\n[OK] Setup complete! Discord should detect the app.",
                Colors.GREEN, bold=True,
            )
            print_color("[!] Discord MUST be running for detection to work", Colors.YELLOW)
            print_color("[*] Keep the process running until the quest is complete", Colors.CYAN)

        input(f"\n{Colors.GRAY}Press Enter to continue...{Colors.RESET}")
        return