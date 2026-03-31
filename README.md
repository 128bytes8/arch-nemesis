# Arch-Nemesis

**YouTube Live Chat controls a real Arch Linux VM** – hardened against NSFW content and system destruction.

## Defence Layers

| Layer | Where | What it does |
|:------|:------|:-------------|
| **DNS Filtering** | Guest VM | CleanBrowsing Family Filter blocks adult content at the resolver level |
| **Hosts Blocklist** | Guest VM | 100k+ NSFW domains sinkholed via `/etc/hosts` (StevenBlack + oisd + UT1) |
| **Firewall** | Guest VM | iptables forces all DNS through filtered resolver; blocks DoT, VPN, Tor ports |
| **SafeSearch** | Guest VM | Google, YouTube, Bing forced to safe/restricted mode via hosts entries |
| **Text Filter** | Host | NSFW keywords, blocked domains, and dangerous commands rejected before reaching VM |
| **Rate Limiter** | Host | Per-user command throttling prevents spam |
| **AI Screen Monitor** | Host (optional) | NudeNet scans VM screenshots and auto-closes NSFW windows |
| **System Hardening** | Guest VM | Shutdown/reboot masked, dangerous binaries replaced, critical files immutable |

## Project Structure

```
host/              Host-side Python controller
  controller.py      Main chat → VM bridge
  content_filter.py  NSFW text/URL/command filtering
  rate_limiter.py    Per-user rate limiting
  screen_monitor.py  Optional AI screenshot monitoring
  config.py          Tuneable constants
  requirements.txt   Python dependencies

guest/             Scripts to run inside the VM (as root)
  harden_vm.sh       Anti-brick system hardening
  setup_content_filter.sh  DNS + hosts + firewall NSFW filtering

overlay/           OBS Browser Source overlays
  index.html         Live command log + filter status
  commands.html      Viewer cheatsheet
```

## Viewer Commands

| Command | Action |
|:--------|:-------|
| `!type [text]` | Type a string (NSFW/dangerous content filtered) |
| `!key [name]` | Press a key or combo (`enter`, `ctrl-c`, `alt-tab`) |
| `!mouse [x] [y]` | Move cursor (0-100 scale) |
| `!click [left\|right\|middle]` | Click a mouse button |
| `[single char]` | Quick key press |

## Setup

### 1. Guest VM Setup (run inside the Arch VM as root)

```bash
# Step 1: Install NSFW content filter (MUST run before hardening)
sudo bash guest/setup_content_filter.sh

# Verify DNS filtering works:
nslookup pornhub.com   # should return 0.0.0.0 or NXDOMAIN

# Step 2: Harden against bricking (locks down everything from step 1)
sudo bash guest/harden_vm.sh
# SAVE the secret chattr name printed at the end!
```

### 2. Host Setup

```bash
python -m venv venv
./venv/bin/pip install -r host/requirements.txt

# Basic usage:
./venv/bin/python host/controller.py --video-id VIDEO_ID --vm-name archlinux

# With AI screen monitoring (install nudenet + Pillow first):
./venv/bin/pip install nudenet Pillow
./venv/bin/python host/controller.py --video-id VIDEO_ID --screen-monitor
```

### 3. OBS Setup

Add as Browser Sources:
- `overlay/index.html` – live command log + blocked commands
- `overlay/commands.html` – viewer cheatsheet

### CLI Options

```
--video-id ID         YouTube livestream video ID (required)
--vm-name NAME        libvirt VM name (default: archlinux)
--rate-limit N        Max commands per user per minute (default: 12)
--cooldown SECS       Min seconds between commands (default: 1.0)
--extra-keywords FILE Extra NSFW keywords file (one per line)
--extra-domains FILE  Extra blocked domains file (one per line)
--screen-monitor      Enable AI screenshot NSFW detection
--monitor-interval S  Screenshot check interval (default: 5s)
--nsfw-threshold F    NudeNet confidence threshold (default: 0.45)
```

## Extending the Blocklists

Add custom keywords or domains without modifying source code:

```bash
# Extra keywords (one per line)
echo "custom_bad_word" >> extra_keywords.txt

# Extra domains (one per line)
echo "badsite.com" >> extra_domains.txt

# Use them:
python host/controller.py --video-id ID \
    --extra-keywords extra_keywords.txt \
    --extra-domains extra_domains.txt
```
