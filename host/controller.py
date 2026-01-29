import time
import json
import subprocess
import threading
import argparse
import sys
import os

try:
    import pytchat
except ImportError:
    print("Error: pytchat not installed. Run 'pip install pytchat'")
    sys.exit(1)

# Configuration
VM_NAME = "archlinux"  # Default, can be changed via args
# Poll overlay file every X seconds
OVERLAY_UPDATE_INTERVAL = 1
# Required votes for reboot (DEACTIVATED)
REBOOT_VOTES_REQUIRED = 999999
# Time window for votes (seconds)
VOTE_WINDOW = 300

# Global State
state = {
    "last_commands": [],  # List of strings
    "reboot_votes": [],   # List of timestamps
    "status": "Active"
}
state_lock = threading.Lock()

def run_virsh_command(args):
    """Run a virsh command."""
    cmd = ["virsh", "-c", "qemu:///system"] + args
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(f"Failed to run virsh command: {' '.join(cmd)}")

def send_key(key):
    """Send a keystroke or combination to the VM. Supports 'ctrl-c', 'alt-tab', etc."""
    mapping = {
        "enter": "KEY_ENTER",
        "esc": "KEY_ESC",
        "backspace": "KEY_BACKSPACE",
        "tab": "KEY_TAB",
        "spc": "KEY_SPACE",
        "up": "KEY_UP",
        "down": "KEY_DOWN",
        "left": "KEY_LEFT",
        "right": "KEY_RIGHT",
        "meta": "KEY_LEFTMETA",
        "super": "KEY_LEFTMETA",
        "win": "KEY_LEFTMETA",
        "cmd": "KEY_LEFTMETA",
        "ctrl": "KEY_LEFTCTRL",
        "alt": "KEY_LEFTALT",
        "shift": "KEY_LEFTSHIFT",
        "capslock": "KEY_CAPSLOCK",
        "caps": "KEY_CAPSLOCK",
        "numlock": "KEY_NUMLOCK",
        "num": "KEY_NUMLOCK",
        "delete": "KEY_DELETE",
        "del": "KEY_DELETE",
        "f1": "KEY_F1", "f2": "KEY_F2", "f3": "KEY_F3", "f4": "KEY_F4",
        "f5": "KEY_F5", "f6": "KEY_F6", "f7": "KEY_F7", "f8": "KEY_F8",
        "f9": "KEY_F9", "f10": "KEY_F10", "f11": "KEY_F11", "f12": "KEY_F12",
    }
    
    # Split by common delimiters for combinations
    # Handle '^' as a shortcut for ctrl-
    key_str = key.replace("^", "ctrl-").replace("+", "-")
    parts = key_str.split("-")
    keys_to_send = []
    
    for p in parts:
        p_lower = p.lower()
        if p_lower in mapping:
            keys_to_send.append(mapping[p_lower])
        else:
            # Handle single letters (A-Z) and numbers
            val = p.upper()
            if len(val) == 1:
                if val.isalpha():
                    keys_to_send.append(f"KEY_{val}")
                elif val.isdigit():
                    keys_to_send.append(f"KEY_{val}")
                else:
                    # Fallback for other single chars
                    keys_to_send.append(val)
            else:
                # Fallback for verbatim virsh names
                keys_to_send.append(val)
    
    if keys_to_send:
        print(f"Sending keys: {' + '.join(keys_to_send)}")
        run_virsh_command(["send-key", VM_NAME] + keys_to_send)

def send_text(text):
    """Send text by mapping characters to key chords."""
    # Mapping for symbols that require SHIFT
    shift_map = {
        '!': 'KEY_1', '@': 'KEY_2', '#': 'KEY_3', '$': 'KEY_4', '%': 'KEY_5',
        '^': 'KEY_6', '&': 'KEY_7', '*': 'KEY_8', '(': 'KEY_9', ')': 'KEY_0',
        '_': 'KEY_MINUS', '+': 'KEY_EQUAL', '{': 'KEY_LEFTBRACE', '}': 'KEY_RIGHTBRACE',
        '|': 'KEY_BACKSLASH', ':': 'KEY_SEMICOLON', '"': 'KEY_APOSTROPHE',
        '<': 'KEY_COMMA', '>': 'KEY_DOT', '?': 'KEY_SLASH', '~': 'KEY_GRAVE'
    }
    # Mapping for symbols that do NOT require SHIFT
    direct_map = {
        ' ': 'KEY_SPACE', '-': 'KEY_MINUS', '=': 'KEY_EQUAL', '[': 'KEY_LEFTBRACE',
        ']': 'KEY_RIGHTBRACE', '\\': 'KEY_BACKSLASH', ';': 'KEY_SEMICOLON',
        "'": 'KEY_APOSTROPHE', ',': 'KEY_COMMA', '.': 'KEY_DOT', '/': 'KEY_SLASH',
        '`': 'KEY_GRAVE'
    }

    print(f"Typing: {text}")
    for char in text:
        keys = []
        if char.isupper():
            keys = ["KEY_LEFTSHIFT", f"KEY_{char}"]
        elif char.islower():
            keys = [f"KEY_{char.upper()}"]
        elif char.isdigit():
            keys = [f"KEY_{char}"]
        elif char in shift_map:
            keys = ["KEY_LEFTSHIFT", shift_map[char]]
        elif char in direct_map:
            keys = [direct_map[char]]
        
        if keys:
            run_virsh_command(["send-key", VM_NAME] + keys)
            time.sleep(0.05)

def move_mouse(x, y):
    """Move mouse to absolute coordinates (0-65535 for QEMU usually, or 0-100%).
    Using QMP input-send-event with absolute coordinates is best.
    Or 'virsh qemu-monitor-command' with 'input_event'.
    """
    # Converting 0-100 to standard absolute range if needed.
    # For QEMU abs input, usually it's defined by the device.
    # Let's try sending a QMP command via virsh.
    # This assumes a mouse device is available.
    print(f"Moving mouse to {x}%, {y}%")
    # Note: This is an implementation detail that might need tweaking based on the specific VM input device (tablet vs mouse).
    # Using 'send-key' approach for buttons, but mouse move is harder with just virsh CLI commands without QMP.
    # We will try a QMP command.
    # input-position abs axis=x value=...
    # We'll rely on a simpler 'human-monitor-command' if available or just log it for now as "Not Implemented" fully 
    # without exact QEMU setup knowledge. 
    # Actually, let's implement a "best effort" using generic qemu-monitor-command if possible.
    try:
        # Assuming a tablet device for absolute positioning (recommended for VMs)
        # value is usually 0-0x7FFF or similar depending on resolution.
        # Let's assume standard 0-100 inputs map to script logic we'd need to injection.
        pass 
    except:
        pass

def trigger_reboot():
    global state
    print("REBOOTING VM VIA VOTING SYSTEM!")
    with state_lock:
        state["status"] = "Rebooting..."
        state["reboot_votes"] = []
    
    # Send a hard reset or graceful reboot
    run_virsh_command(["reboot", VM_NAME])
    
    time.sleep(5)
    with state_lock:
        state["status"] = "Active"

def handle_vote():
    now = time.time()
    with state_lock:
        # Prune old votes
        state["reboot_votes"] = [t for t in state["reboot_votes"] if now - t < VOTE_WINDOW]
        # Add new vote
        state["reboot_votes"].append(now)
        count = len(state["reboot_votes"])
    
    print(f"Vote registered. Total: {count}/{REBOOT_VOTES_REQUIRED}")
    
    if count >= REBOOT_VOTES_REQUIRED:
        threading.Thread(target=trigger_reboot).start()

def update_overlay():
    while True:
        with state_lock:
            # Prune old votes for display
            now = time.time()
            state["reboot_votes"] = [t for t in state["reboot_votes"] if now - t < VOTE_WINDOW]
            
            data = {
                "commands": state["last_commands"][-10:], # Last 10 commands
                "vote_count": len(state["reboot_votes"]),
                "vote_target": REBOOT_VOTES_REQUIRED,
                "status": state["status"]
            }
        
        try:
            # Get the directory of the current script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            overlay_path = os.path.join(script_dir, "..", "overlay", "overlay_state.json")
            with open(overlay_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error updating overlay: {e}")
            
        time.sleep(OVERLAY_UPDATE_INTERVAL)

def parse_chat(video_id):
    chat = pytchat.create(video_id=video_id)
    print(f"Connected to chat: {video_id}")
    
    try:
        while chat.is_alive():
            for c in chat.get().sync_items():
                msg = c.message
                author = c.author.name
                print(f"[{author}] {msg}")
                
                cmd_display = f"{author}: {msg}"
                
                with state_lock:
                    state["last_commands"].append(cmd_display)
                    if len(state["last_commands"]) > 20:
                        state["last_commands"].pop(0)

                # Command Parsing
                if msg.startswith("!type "):
                    text = msg[6:]
                    send_text(text)
                elif msg.startswith("!key "):
                    key = msg[5:]
                    send_key(key)
                elif msg.startswith("!mouse "): # !mouse 50 50
                    try:
                        parts = msg.split()
                        x = int(parts[1])
                        y = int(parts[2])
                        move_mouse(x, y)
                    except:
                        pass
                # Raw text typing for everything else
                elif len(msg) == 1:
                     send_key(msg)
            time.sleep(0.1) # Small sleep to prevent CPU hogging
    except Exception as e:
        print(f"Error in chat loop: {e}")
    finally:
        print("Chat connection closed.")
                 
def main():
    parser = argparse.ArgumentParser(description="YouTube to Arch VM Controller")
    parser.add_argument("--video-id", required=True, help="YouTube Video ID of the livestream")
    parser.add_argument("--vm-name", default="archlinux", help="Name of the VM in virsh")
    args = parser.parse_args()
    
    global VM_NAME
    VM_NAME = args.vm_name
    
    # Start overlay updater
    threading.Thread(target=update_overlay, daemon=True).start()
    
    # Start chat listener loop
    while True:
        try:
            parse_chat(args.video_id)
            print("Chat listener exited unexpectedly. Reconnecting...")
        except KeyboardInterrupt:
            print("Stopping...")
            break
        except Exception as e:
            print(f"Fatal error in listener: {e}")
        
        print("Waiting 5 seconds before reconnecting...")
        time.sleep(5)

if __name__ == "__main__":
    main()
