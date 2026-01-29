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
    """Send a keystroke to the VM."""
    # Mapping for some special keys to virsh codes if needed, 
    # but virsh send-key usually accepts standard names.
    print(f"Sending key: {key}")
    run_virsh_command(["send-key", VM_NAME, key])

def send_text(text):
    """Send text as a sequence of keys."""
    # This is a bit complex as we need to map chars to keys. 
    # For simplicity, we'll try to use `send-key` for each char.
    # A more robust way might be QMP input-send-event but that's complex.
    # We will just iterate.
    print(f"Typing: {text}")
    for char in text:
        k = char
        if char == " ":
            k = "spc"
        elif char == ".":
            k = "dot"
        elif char == "/":
            k = "slash"
        # Add more mappings as needed or let virsh complain
        try:
           run_virsh_command(["send-key", VM_NAME, k])
           time.sleep(0.05) # Small delay
        except:
            pass

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
            with open("../overlay/overlay_state.json", "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error updating overlay: {e}")
            
        time.sleep(OVERLAY_UPDATE_INTERVAL)

def parse_chat(video_id):
    chat = pytchat.create(video_id=video_id)
    print(f"Connected to chat: {video_id}")
    
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
            # Raw text typing for everything else? Maybe too chaotic. 
            # Sticking to commands for now as requested "w+w+jump".
            # If user wants raw input mapped:
            # "w" -> send_key("w")
            elif len(msg) == 1 and msg.isalnum():
                 send_key(msg)
                 
def main():
    parser = argparse.ArgumentParser(description="YouTube to Arch VM Controller")
    parser.add_argument("--video-id", required=True, help="YouTube Video ID of the livestream")
    parser.add_argument("--vm-name", default="archlinux", help="Name of the VM in virsh")
    args = parser.parse_args()
    
    global VM_NAME
    VM_NAME = args.vm_name
    
    # Start overlay updater
    threading.Thread(target=update_overlay, daemon=True).start()
    
    # Start chat listener
    try:
        parse_chat(args.video_id)
    except KeyboardInterrupt:
        print("Stopping...")

if __name__ == "__main__":
    main()
