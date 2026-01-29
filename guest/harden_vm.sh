#!/bin/bash
# Guest Hardening Script
# Run this inside the Arch VM as root

echo "Hardening VM against shutdown..."

# 1. Mask systemd targets (PERMANENT)
# Masking these prevents systemd from reaching power-off states.
systemctl mask poweroff.target reboot.target halt.target shutdown.target
# Manually remove the symlink if mask didn't catch the multi-user dependency
rm -f /etc/systemd/system/multi-user.target.wants/reboot.target 2>/dev/null

# 2. Replace binaries with dummies and make them IMMUTABLE
# We want to prevent 'shutdown', 'passwd', 'usermod', etc. from working.
# Even if they try to 'rm' these as root, chattr +i will stop them.

FORBIDDEN_CMDS="shutdown poweroff reboot halt passwd usermod useradd userdel groupmod groupadd groupdel chsh"

for cmd in $FORBIDDEN_CMDS; do
    if [ -f "/sbin/$cmd" ]; then
        mv "/sbin/$cmd" "/sbin/$cmd.bak"
        chattr +i "/sbin/$cmd.bak" 2>/dev/null
    fi
    if [ -f "/usr/bin/$cmd" ]; then
        mv "/usr/bin/$cmd" "/usr/bin/$cmd.bak"
        chattr +i "/usr/bin/$cmd.bak" 2>/dev/null
    fi
    
    # Create dummy
    DUMMY_PATH="/usr/bin/$cmd"
    # Some commands are in /sbin, but usually symlinked to /usr/bin in Arch
    echo '#!/bin/bash' > "$DUMMY_PATH"
    echo 'echo "Command disabled! Account/System changes are forbidden."' >> "$DUMMY_PATH"
    chmod +x "$DUMMY_PATH"
    chattr +i "$DUMMY_PATH" 2>/dev/null
done

# 3. Protect Identity files
# Making these immutable prevents any changes to users or passwords
echo "Locking down /etc/passwd, /etc/shadow, etc..."
chattr +i /etc/passwd /etc/shadow /etc/group /etc/gshadow 2>/dev/null

# 4. Protect the hardening script itself
# This prevents users from deleting this script if it's left on the system.
SCRIPT_PATH="$(realpath "$0")"
echo "Making $SCRIPT_PATH immutable..."
chattr +i "$SCRIPT_PATH" 2>/dev/null

# 4. Protect systemd units
# Make the mask links harder to remove
chattr +i /etc/systemd/system/poweroff.target 2>/dev/null
chattr +i /etc/systemd/system/reboot.target 2>/dev/null
chattr +i /etc/systemd/system/halt.target 2>/dev/null
chattr +i /etc/systemd/system/shutdown.target 2>/dev/null

# 5. Restrict 'chattr' itself? 
# This is the "nuclear option" to prevent them from undoing +i.
# We rename it to something secret only you know.
SECRET_CHATTR_NAME="chattr_secret_$(date +%s | tail -c 5)"
echo "Renaming chattr to $SECRET_CHATTR_NAME to prevent reversals."
mv /usr/bin/chattr "/usr/bin/$SECRET_CHATTR_NAME"
echo "IMPORTANT: To undo hardening, you must use /usr/bin/$SECRET_CHATTR_NAME"

echo "Hardening complete. The system is now significantly more resistant to chat-driven sabotage."
