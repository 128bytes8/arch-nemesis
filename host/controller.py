#!/usr/bin/env python3
"""
Arch-Nemesis Controller
───────────────────────
Reads YouTube Live chat and forwards viewer commands to a libvirt/QEMU
VM while enforcing multi-layered content and safety filtering.

Usage:
    python controller.py --video-id VIDEO_ID [--vm-name archlinux] [--screen-monitor]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time

# ── Local modules ─────────────────────────────────────────────────────
from config import (
    COMMAND_COOLDOWN,
    DEFAULT_VM_NAME,
    INTERNAL_LOG_LENGTH,
    KEY_SEND_DELAY,
    MAX_COMMANDS_PER_MINUTE,
    MAX_TYPE_LENGTH,
    NSFW_CONFIDENCE_THRESHOLD,
    OVERLAY_LOG_LENGTH,
    OVERLAY_UPDATE_INTERVAL,
    REBOOT_VOTES_REQUIRED,
    SCREEN_MONITOR_INTERVAL,
    VIRSH_URI,
    VOTE_WINDOW,
)
from content_filter import ContentFilter
from rate_limiter import RateLimiter
from screen_monitor import ScreenMonitor

try:
    from chat_downloader import ChatDownloader
except ImportError:
    print("FATAL: chat-downloader not installed.  Run:  pip install chat-downloader")
    sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("archnemesis")

# ── Globals (set in main()) ───────────────────────────────────────────
VM_NAME: str = DEFAULT_VM_NAME

state_lock = threading.Lock()
state: dict = {
    "last_commands": [],
    "blocked_commands": [],
    "reboot_votes": [],
    "status": "Active",
}

# ═══════════════════════════════════════════════════════════════════════
#  VIRSH HELPERS
# ═══════════════════════════════════════════════════════════════════════

def run_virsh(args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["virsh", "-c", VIRSH_URI] + args
    try:
        return subprocess.run(
            cmd, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        log.debug("virsh failed: %s", " ".join(cmd))
        return exc  # type: ignore[return-value]


def run_virsh_qmp(qmp_json: str) -> None:
    subprocess.run(
        ["virsh", "-c", VIRSH_URI, "qemu-monitor-command", VM_NAME, qmp_json],
        capture_output=True,
    )


# ═══════════════════════════════════════════════════════════════════════
#  INPUT: KEYBOARD
# ═══════════════════════════════════════════════════════════════════════

KEY_MAP: dict[str, str] = {
    "enter": "KEY_ENTER", "esc": "KEY_ESC", "backspace": "KEY_BACKSPACE",
    "tab": "KEY_TAB", "spc": "KEY_SPACE", "space": "KEY_SPACE",
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "meta": "KEY_LEFTMETA", "super": "KEY_LEFTMETA", "win": "KEY_LEFTMETA",
    "ctrl": "KEY_LEFTCTRL", "alt": "KEY_LEFTALT", "shift": "KEY_LEFTSHIFT",
    "capslock": "KEY_CAPSLOCK", "caps": "KEY_CAPSLOCK",
    "numlock": "KEY_NUMLOCK", "num": "KEY_NUMLOCK",
    "delete": "KEY_DELETE", "del": "KEY_DELETE",
    "insert": "KEY_INSERT", "ins": "KEY_INSERT",
    "home": "KEY_HOME", "end": "KEY_END",
    "pageup": "KEY_PAGEUP", "pgup": "KEY_PAGEUP",
    "pagedown": "KEY_PAGEDOWN", "pgdn": "KEY_PAGEDOWN",
    "f1": "KEY_F1", "f2": "KEY_F2", "f3": "KEY_F3", "f4": "KEY_F4",
    "f5": "KEY_F5", "f6": "KEY_F6", "f7": "KEY_F7", "f8": "KEY_F8",
    "f9": "KEY_F9", "f10": "KEY_F10", "f11": "KEY_F11", "f12": "KEY_F12",
}

SHIFT_MAP: dict[str, str] = {
    '!': 'KEY_1', '@': 'KEY_2', '#': 'KEY_3', '$': 'KEY_4', '%': 'KEY_5',
    '^': 'KEY_6', '&': 'KEY_7', '*': 'KEY_8', '(': 'KEY_9', ')': 'KEY_0',
    '_': 'KEY_MINUS', '+': 'KEY_EQUAL', '{': 'KEY_LEFTBRACE',
    '}': 'KEY_RIGHTBRACE', '|': 'KEY_BACKSLASH', ':': 'KEY_SEMICOLON',
    '"': 'KEY_APOSTROPHE', '<': 'KEY_COMMA', '>': 'KEY_DOT',
    '?': 'KEY_SLASH', '~': 'KEY_GRAVE',
}

DIRECT_MAP: dict[str, str] = {
    ' ': 'KEY_SPACE', '-': 'KEY_MINUS', '=': 'KEY_EQUAL',
    '[': 'KEY_LEFTBRACE', ']': 'KEY_RIGHTBRACE', '\\': 'KEY_BACKSLASH',
    ';': 'KEY_SEMICOLON', "'": 'KEY_APOSTROPHE', ',': 'KEY_COMMA',
    '.': 'KEY_DOT', '/': 'KEY_SLASH', '`': 'KEY_GRAVE',
}


def send_key(key: str) -> None:
    """Send a named key or chord (e.g. ``ctrl-c``, ``alt-tab``)."""
    key_str = key.replace("^", "ctrl-").replace("+", "-")
    parts = key_str.split("-")
    keys: list[str] = []
    for p in parts:
        low = p.lower()
        if low in KEY_MAP:
            keys.append(KEY_MAP[low])
        elif len(p) == 1 and p.isalpha():
            keys.append(f"KEY_{p.upper()}")
        elif len(p) == 1 and p.isdigit():
            keys.append(f"KEY_{p}")
        else:
            keys.append(p.upper())  # verbatim fallback
    if keys:
        log.info("  ⌨  %s", " + ".join(keys))
        run_virsh(["send-key", VM_NAME] + keys)


def send_text(text: str) -> None:
    """Type a string character-by-character."""
    log.info("  ⌨  typing %d chars", len(text))
    for ch in text:
        keys: list[str] = []
        if ch.isupper():
            keys = ["KEY_LEFTSHIFT", f"KEY_{ch}"]
        elif ch.islower():
            keys = [f"KEY_{ch.upper()}"]
        elif ch.isdigit():
            keys = [f"KEY_{ch}"]
        elif ch in SHIFT_MAP:
            keys = ["KEY_LEFTSHIFT", SHIFT_MAP[ch]]
        elif ch in DIRECT_MAP:
            keys = [DIRECT_MAP[ch]]
        if keys:
            run_virsh(["send-key", VM_NAME] + keys)
            time.sleep(KEY_SEND_DELAY)


# ═══════════════════════════════════════════════════════════════════════
#  INPUT: MOUSE  (requires USB-tablet device in VM config)
# ═══════════════════════════════════════════════════════════════════════

def move_mouse(x_pct: int, y_pct: int) -> None:
    """Move cursor to an absolute position (0-100 %)."""
    x_pct = max(0, min(100, x_pct))
    y_pct = max(0, min(100, y_pct))
    x = int(x_pct / 100 * 32767)
    y = int(y_pct / 100 * 32767)
    qmp = json.dumps({
        "execute": "input-send-event",
        "arguments": {"events": [
            {"type": "abs", "data": {"axis": "x", "value": x}},
            {"type": "abs", "data": {"axis": "y", "value": y}},
        ]},
    })
    log.info("  🖱  move → %d%%, %d%%", x_pct, y_pct)
    run_virsh_qmp(qmp)


def click_mouse(button: str = "left") -> None:
    """Press and release a mouse button."""
    btn_qmp = {"left": "left", "right": "right", "middle": "middle"}.get(button, "left")
    for down in (True, False):
        qmp = json.dumps({
            "execute": "input-send-event",
            "arguments": {"events": [
                {"type": "btn", "data": {"down": down, "button": btn_qmp}},
            ]},
        })
        run_virsh_qmp(qmp)
        if down:
            time.sleep(0.05)
    log.info("  🖱  click %s", btn_qmp)


# ═══════════════════════════════════════════════════════════════════════
#  REBOOT VOTING  (effectively disabled at 999 999 votes)
# ═══════════════════════════════════════════════════════════════════════

def handle_vote() -> None:
    now = time.time()
    with state_lock:
        votes = [t for t in state["reboot_votes"] if now - t < VOTE_WINDOW]
        votes.append(now)
        state["reboot_votes"] = votes
    log.info("  Vote registered (%d/%d)", len(votes), REBOOT_VOTES_REQUIRED)
    if len(votes) >= REBOOT_VOTES_REQUIRED:
        threading.Thread(target=_do_reboot, daemon=True).start()


def _do_reboot() -> None:
    log.warning("REBOOTING VM (vote threshold reached)")
    with state_lock:
        state["status"] = "Rebooting..."
        state["reboot_votes"] = []
    run_virsh(["reboot", VM_NAME])
    time.sleep(5)
    with state_lock:
        state["status"] = "Active"


# ═══════════════════════════════════════════════════════════════════════
#  OVERLAY JSON WRITER
# ═══════════════════════════════════════════════════════════════════════

def overlay_loop() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    overlay_path = os.path.join(script_dir, "..", "overlay", "overlay_state.json")
    while True:
        now = time.time()
        with state_lock:
            state["reboot_votes"] = [
                t for t in state["reboot_votes"] if now - t < VOTE_WINDOW
            ]
            data = {
                "commands": state["last_commands"][-OVERLAY_LOG_LENGTH:],
                "blocked": state["blocked_commands"][-5:],
                "vote_count": len(state["reboot_votes"]),
                "vote_target": REBOOT_VOTES_REQUIRED,
                "status": state["status"],
            }
        try:
            with open(overlay_path, "w") as f:
                json.dump(data, f)
        except OSError as exc:
            log.error("Overlay write error: %s", exc)
        time.sleep(OVERLAY_UPDATE_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════
#  STATE HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _add_command(author: str, msg: str) -> None:
    entry = f"{author}: {msg}"
    with state_lock:
        state["last_commands"].append(entry)
        if len(state["last_commands"]) > INTERNAL_LOG_LENGTH:
            state["last_commands"].pop(0)


def _add_blocked(author: str, reason: str) -> None:
    entry = f"{author} blocked – {reason}"
    with state_lock:
        state["blocked_commands"].append(entry)
        if len(state["blocked_commands"]) > 10:
            state["blocked_commands"].pop(0)


# ═══════════════════════════════════════════════════════════════════════
#  CHAT LOOP
# ═══════════════════════════════════════════════════════════════════════

def parse_chat(
    video_id: str,
    content_filter: ContentFilter,
    rate_limiter: RateLimiter,
) -> None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    chat = ChatDownloader().get_chat(url, message_groups=["messages"])
    log.info("Connected to YouTube chat: %s", video_id)

    try:
        for item in chat:
            msg: str = (item.get("message") or "").strip()
            author: str = item.get("author", {}).get("name", "Unknown")

            if not msg:
                continue

            log.info("[%s] %s", author, msg)

            # ── Rate limit ────────────────────────────────────────
            if not rate_limiter.is_allowed(author):
                log.debug("Rate-limited: %s", author)
                continue

            _add_command(author, msg)

            # ── !type <text> ──────────────────────────────────────
            if msg.startswith("!type "):
                text = msg[6:]
                if len(text) > MAX_TYPE_LENGTH:
                    log.warning("Text too long from %s (%d chars)", author, len(text))
                    _add_blocked(author, f"text too long ({len(text)} chars)")
                    continue
                ok, reason = content_filter.filter_type_command(text)
                if not ok:
                    log.warning("BLOCKED !type from %s: %s", author, reason)
                    _add_blocked(author, reason)
                    continue
                send_text(text)

            # ── !key <name> ───────────────────────────────────────
            elif msg.startswith("!key "):
                key = msg[5:].strip()
                if not key:
                    continue
                ok, reason = content_filter.filter_key_command(key)
                if not ok:
                    log.warning("BLOCKED !key from %s: %s", author, reason)
                    _add_blocked(author, reason)
                    continue
                send_key(key)

            # ── !mouse x y ────────────────────────────────────────
            elif msg.startswith("!mouse "):
                try:
                    parts = msg.split()
                    x, y = int(parts[1]), int(parts[2])
                    move_mouse(x, y)
                except (IndexError, ValueError):
                    pass

            # ── !click [button] ───────────────────────────────────
            elif msg.startswith("!click"):
                parts = msg.split()
                button = parts[1].lower() if len(parts) > 1 else "left"
                click_mouse(button)

            # ── !vote (reboot) ────────────────────────────────────
            elif msg.strip() == "!vote":
                handle_vote()

            # ── Single-character shortcut ─────────────────────────
            elif len(msg) == 1:
                send_key(msg)

    except Exception as exc:
        log.error("Chat loop error: %s", exc)
    finally:
        log.info("Chat connection closed")


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Arch-Nemesis: YouTube Chat → VM Controller (hardened)",
    )
    parser.add_argument("--video-id", required=True, help="YouTube live-stream video ID")
    parser.add_argument("--vm-name", default=DEFAULT_VM_NAME, help="libvirt VM name")

    # Content filtering
    parser.add_argument("--extra-keywords", help="File with extra NSFW keywords (one per line)")
    parser.add_argument("--extra-domains", help="File with extra blocked domains (one per line)")

    # Rate limiting
    parser.add_argument("--rate-limit", type=int, default=MAX_COMMANDS_PER_MINUTE,
                        help="Max commands per user per minute")
    parser.add_argument("--cooldown", type=float, default=COMMAND_COOLDOWN,
                        help="Min seconds between commands per user")

    # AI screen monitoring
    parser.add_argument("--screen-monitor", action="store_true",
                        help="Enable AI screenshot NSFW detection (requires nudenet)")
    parser.add_argument("--monitor-interval", type=float, default=SCREEN_MONITOR_INTERVAL,
                        help="Seconds between screenshot checks")
    parser.add_argument("--nsfw-threshold", type=float, default=NSFW_CONFIDENCE_THRESHOLD,
                        help="NudeNet confidence threshold (0-1)")

    args = parser.parse_args()

    global VM_NAME
    VM_NAME = args.vm_name

    # ── Initialise sub-systems ────────────────────────────────────────
    content_filter = ContentFilter(
        extra_keywords_file=args.extra_keywords,
        extra_domains_file=args.extra_domains,
    )
    rate_limiter = RateLimiter(
        max_per_minute=args.rate_limit,
        cooldown=args.cooldown,
    )

    log.info("Content filter loaded: %d keywords, %d domains",
             len(content_filter.nsfw_words), len(content_filter.blocked_domains))

    # Overlay thread
    threading.Thread(target=overlay_loop, daemon=True, name="overlay").start()

    # Optional AI screen monitor
    if args.screen_monitor:
        monitor = ScreenMonitor(
            vm_name=VM_NAME,
            virsh_uri=VIRSH_URI,
            interval=args.monitor_interval,
            threshold=args.nsfw_threshold,
        )
        monitor.start()

    # ── Chat listener (auto-reconnect) ────────────────────────────────
    log.info("Starting Arch-Nemesis controller for VM '%s'", VM_NAME)
    while True:
        try:
            parse_chat(args.video_id, content_filter, rate_limiter)
            log.warning("Chat listener exited – reconnecting in 5s …")
        except KeyboardInterrupt:
            log.info("Shutting down")
            break
        except Exception as exc:
            log.error("Fatal: %s", exc)
        time.sleep(5)


if __name__ == "__main__":
    main()
