"""
Arch-Nemesis Configuration
All tuneable constants in one place.
"""

# ── VM ────────────────────────────────────────────────────────────────
DEFAULT_VM_NAME = "archlinux"
VIRSH_URI = "qemu:///system"

# ── Overlay ───────────────────────────────────────────────────────────
OVERLAY_UPDATE_INTERVAL = 1          # seconds between JSON writes
OVERLAY_LOG_LENGTH = 10              # commands shown in overlay
INTERNAL_LOG_LENGTH = 30             # commands kept in memory

# ── Rate Limiting ─────────────────────────────────────────────────────
MAX_COMMANDS_PER_MINUTE = 12         # per user
COMMAND_COOLDOWN = 1.0               # seconds between commands (per user)

# ── Input Limits ──────────────────────────────────────────────────────
MAX_TYPE_LENGTH = 200                # max chars for a single !type
KEY_SEND_DELAY = 0.05                # seconds between keystrokes in !type

# ── Reboot Voting (effectively disabled) ──────────────────────────────
REBOOT_VOTES_REQUIRED = 999_999
VOTE_WINDOW = 300                    # seconds

# ── Screen Monitor (optional AI layer) ────────────────────────────────
SCREEN_MONITOR_INTERVAL = 5          # seconds between screenshot checks
NSFW_CONFIDENCE_THRESHOLD = 0.45     # NudeNet detection threshold
