<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0a0a0a,60:0d1f0d,100:1a4a1a&height=200&section=header&text=orbshacker&fontSize=70&fontColor=4ade80&fontAlignY=55&animation=fadeIn" width="100%"/>

<br/>

[![Python](https://img.shields.io/badge/Python-3.7+-3572A5?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20Only-555555?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/FyuPuff/orbshacker)
[![Discord](https://img.shields.io/badge/Discord-Game%20Spoofer-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com)
[![License](https://img.shields.io/badge/License-GPL%20v3-c0392b?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](./LICENSE)
[![Version](https://img.shields.io/github/v/release/FyuPuff/orbshacker?style=for-the-badge&logo=semanticrelease&color=4ade80&logoColor=white)](https://github.com/FyuPuff/orbshacker/releases)

<br/>

*Because who has time to install 500GB of games just for some orbs.*

<br/>

[Get Started](#installation) &nbsp;·&nbsp; [How it works](#how-it-works) &nbsp;·&nbsp; [Steam Mode](#steam-quest-mode) &nbsp;·&nbsp; [Usage](#usage) &nbsp;·&nbsp; [Structure](#project-structure) &nbsp;·&nbsp; [Legal](#legal-notice)

</div>

<br/>

<div align="center">
<img width="340" alt="image" src="https://github.com/user-attachments/assets/1db237b0-2f57-428f-a004-d707f98a416e" style="border-radius: 16px"/>
</div>

## What is this

orbshacker is a Windows tool that creates fake game processes for Discord Orb quests without installing the actual games. It reads Discord's own public API to get the exact process names Discord expects, copies a base executable, renames it, and launches it in the background. Discord scans your process list, sees what it's looking for, and marks the quest as active.

No client modification. No code injection. No suspicious network traffic. Just a process name sitting in your task list, which is all Discord ever checks.

> **Educational purposes only.** This tool is provided to study how Discord's game detection system works and to explore process manipulation techniques. Use at your own risk and in compliance with all applicable terms of service.

<br/>

## 🚨 Steam Quest Mode

A lot of games - Marathon, EA Sports FC 27, John Carpenter's Toxic Commando, more than half of Discord's catalogue - are published **without any process name**. There is nothing for Discord to match, so renaming an exe can never work for them. Those games are only recognised through their store.

Steam Quest Mode handles them. Search the game in the tool, and it takes the Steam app id straight from Discord's own database (`third_party_skus`), registers the app as installed in the Windows registry, drops the faked process into the Steam library folder and launches it.

### How it works

Verified against the shipped client (Discord 1.0.9259, `modules/discord_utils-1/discord_utils/discord_utils.node`, compiled from `steam_observer_win.cpp`):

- `SteamObserver::updateInstalledSkus` enumerates the subkeys of `HKCU\SOFTWARE\Valve\Steam\Apps` and treats every subkey **name** as an installed Steam app id.
- `SteamObserver::DetectSteamGame` opens `Software\Valve\Steam\Apps\<appid>` (the format string `Software\Valve\Steam\Apps\%d` is in the binary) and reads values such as `Installed`.
- The **exe path** decides the distributor: a process below `<library>/steamapps/common/` is reported with `distributor: "steam"`. Libraries come from `HKCU\SOFTWARE\Valve\Steam` → `SteamPath` and `<SteamPath>\config\libraryfolders.vdf`.
- Anything the observer cannot attribute to an installed app is flagged `hidden`, and the client drops hidden games *before* reporting an activity. A fake that is not in the registry is silently ignored.
- The client then maps the process to a game by the id it was given, by an exact name/alias match, or by exe path. With no `executables` published, only the **name** can match, so the tool registers Discord's game name (`EA Sports FC 27`, not `EA SPORTS FC™ 27`).

**`appmanifest_<appid>.acf` is never read by Discord.** The strings `appmanifest`, `AppState` and `StateFlags` do not exist anywhere in its binaries. Writing one only makes the fake folder look real and teaches the real Steam client about a game you do not own, so it is optional (`STEAM_WRITE_APPMANIFEST`, on by default) and the registry entry is what actually does the work.

**Supported:**
`Games with no process name` &nbsp; `App id taken from Discord's own data` &nbsp; `Uses your real SteamID` &nbsp; `Auto-cleanup on exit`

> [!] **Keep the Steam client closed** while faking. A running Steam client rewrites the registry and manifests underneath you. If a game does not show up, restart Discord - its observer caches the installed-app list.

<br/>

## Features

**Automatic Game Detection** pulls the latest detectable game list from Discord's official API. Smart search lets you find games by name or abbreviation PUBG, LoL, CSGO. Auto-launch handles everything in the background.

**Self-Executing Timer & Embedded Config** builds faked game processes (renamed copies of the spoofer executable) that directly run the countdown timer when double-clicked by the user, with custom durations and auto-delete settings embedded directly inside the binary. No console windows are allocated for the faked processes. Each timer window is titled with the game it is faking (e.g. `PUBG: Battlegrounds`), so multiple games stay easy to tell apart.

**Automatic Self-Destruction (`AUTO_DELETE`)** cleans up all faked executables, parent folders, and generated Steam manifests in the background once the countdown timer finishes.

**Multi-Game Support** lets you run multiple fake processes simultaneously, completing all orb quests at once. Launch a game, press Enter, pick another, repeat. Each process runs independently and Discord sees all of them.

**No-Process-Name Games** are detected automatically. If Discord publishes no executable for a game, option 1 says so and hands you to Steam Quest Mode with the correct Steam app id already filled in.

**Backup Database** falls back to a GitHub archive if Discord's API is unavailable, so the tool keeps working even when the primary source is down.

**Manual Mode** supports custom executable names if you need to spoof something not in the database.

**Beautiful Interface** is a colored terminal UI with loading animations, because plain text is boring.

<br/>

## Why this method works

Discord's game detection reads your Windows process list. It sees `TslGame.exe` and assumes you're playing PUBG. There is no technical mechanism in place to verify whether that process is the actual game or a renamed executable. The name is all it checks.

To detect this method, Discord would need kernel-level anti-cheat software comparable to Valorant's Vanguard deep system access, raised privacy concerns, a broken promise of being a lightweight chat app. That is not happening for cosmetic orb quests.

**What this is not:** This tool does not inject code into Discord's console, modify client files, or send fake API requests. Those methods leave traces. Discord can detect when their JavaScript has been tampered with. Our approach leaves Discord's client completely untouched. The tool uses Discord's own public API to fetch the game list. No client modification. No integrity violations.

<br/>

## Requirements

Python 3.7 or higher, Windows only. Internet connection for database fetching. Discord must be running the spoofer only works when Discord is active and scanning processes.

<br/>

## Installation

```bash
git clone https://github.com/FyuPuff/orbshacker.git
cd orbshacker
pip install -r requirements.txt
```

<br/>

## Usage

```bash
python orbshacker.py
```

Or via the package entry point:

```bash
python -m orbshacker
```

### Menu options

`1` Search Discord database by name or abbreviation

`2` Manual mode, enter a custom executable name

`3` Steam special quest mode

`4` Credits and project info

`5` Exit

### Completing all quests in 15 minutes

Launch the tool. Select your first game. After the process is launched, press Enter to return to the main menu. Select another game. Repeat as many times as needed no need to open multiple windows. Every fake process runs in parallel. Discord detects all of them simultaneously. Wait 15 minutes. Close everything when done.

<br/>

## How it works

The tool connects to Discord's official API (`/api/v9/applications/detectable`) to get the live game list. It extracts the exact process name Discord expects for each game. It copies the spoofer executable (or base Python interpreter in source mode) to the configured folder (defaults to `Desktop/Win64/`), renames it to match the game's executable name, and bakes the active configuration directly inside it.

When the faked game executable runs, it acts as a standalone countdown timer with its settings embedded. When the countdown completes, it automatically triggers a background self-destruction script (if `AUTO_DELETE` is enabled) to delete the faked files and empty parent directories.

Steam Quest Mode adds a layer: it registers the app in the Steam registry, writes an optional `appmanifest_<appid>.acf`, and places the executable in `steamapps/common/<installdir>/`, which is what Discord's Steam observer looks at. It is required for games Discord publishes without a process name.

<br/>

## Project Structure

```
orbshacker/
├── orbshacker.py          Main entry point
├── orbshacker/
│   ├── __init__.py        Version and author metadata
│   ├── __main__.py        Package entry point, --timer-mode support
│   ├── config.py          Centralized configuration with settings.py overrides
│   ├── faker.py           Fake executable creation and launch logic
│   ├── discord_db.py      Game database loading, search, and selection
│   ├── steam.py           Steam registry helpers and manifest generation
│   ├── updater.py         Auto-update from GitHub releases
│   ├── net.py             HTTP helpers
│   ├── ui.py              Terminal colors, animations, prompts
│   └── errors.py          Custom exception hierarchy
├── tests/                 pytest coverage for pure helpers
├── settings.py            User-editable configuration
├── requirements.txt
└── .github/
    └── workflows/
        └── release.yml    PyInstaller build and GitHub Release automation
```

<br/>

## Configuration

User-editable values live in `settings.py` at the project root. The file is loaded at startup and overrides any default from `orbshacker/config.py`. Runtime preferences and API timeouts go there. The application version comes from the git tag used for the build and is not user-configurable; changing it manually would break update detection.

<br/>

## Auto-updater

When a new version tag is pushed, GitHub Actions builds a standalone Windows executable using PyInstaller and publishes it as a GitHub Release. The tool checks for updates on launch, downloads the new binary, swaps it in place, and restarts automatically. No Python installation needed to run the distributed executable.

<br/>

## Legal Notice

**Educational purposes only. No commercial use.**

This tool is provided strictly for educational and research purposes to study how Discord's game detection system works and to explore process manipulation techniques. Commercial use, distribution, or sale is strictly prohibited.

Users are solely responsible for compliance with all applicable laws, Discord's Terms of Service, and any other relevant agreements. The developers do not condone misuse and are not responsible for any consequences resulting from use of this software. No warranties or guarantees are provided. Use at your own risk.

Misuse of this tool may violate Discord's Terms of Service.

<br/>

## License

GPL v3. Attribution required. Modified versions must also be GPL v3. Source code must be provided with any distribution. Commercial use is strictly prohibited. See [LICENSE](./LICENSE) for full terms.

<br/>

<div align="center">

made with questionable life choices by **Strykey**

<br/>

[![GitHub stars](https://img.shields.io/github/stars/FyuPuff/orbshacker?style=for-the-badge&color=4ade80&labelColor=1a1a1a)](https://github.com/FyuPuff/orbshacker/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/FyuPuff/orbshacker?style=for-the-badge&color=4ade80&labelColor=1a1a1a)](https://github.com/FyuPuff/orbshacker/network)

<br/>

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:4ade80,40:0d1f0d,100:0a0a0a&height=120&section=footer" width="100%"/>

</div>
