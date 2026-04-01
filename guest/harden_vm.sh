#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  Arch-Nemesis  –  VM Anti-Brick Hardening Script
# ═══════════════════════════════════════════════════════════════════════
#  Run ONCE inside the guest VM as root.  Makes it extremely difficult
#  for chat-driven commands to brick, shutdown, or sabotage the system.
#
#  Usage:   sudo bash harden_vm.sh
#  Undo:    Use the secret chattr name printed at the end.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root."
    exit 1
fi

echo "═══════════════════════════════════════════════"
echo "  Arch-Nemesis VM Hardening"
echo "═══════════════════════════════════════════════"
echo ""

# -------------------------------------------------------------------
# 1.  MASK SHUTDOWN / REBOOT TARGETS
# -------------------------------------------------------------------
echo "[1/12] Masking shutdown & reboot systemd targets …"
for target in poweroff reboot halt shutdown kexec; do
    systemctl mask "${target}.target" 2>/dev/null || true
done
rm -f /etc/systemd/system/multi-user.target.wants/reboot.target 2>/dev/null || true

# Also mask the ctrl-alt-del handler
systemctl mask ctrl-alt-del.target 2>/dev/null || true
ln -sf /dev/null /etc/systemd/system/ctrl-alt-del.target 2>/dev/null || true

# -------------------------------------------------------------------
# 2.  REPLACE DANGEROUS BINARIES WITH DUMMIES
# -------------------------------------------------------------------
echo "[2/12] Replacing dangerous binaries with stubs …"

FORBIDDEN_CMDS=(
    # Power management
    shutdown poweroff reboot halt
    # Account management
    passwd usermod useradd userdel groupmod groupadd groupdel chsh
    # Destructive disk tools
    dd mkfs fdisk parted wipefs shred sgdisk gdisk cfdisk sfdisk
    mkswap mkfs.ext4 mkfs.btrfs mkfs.xfs mkfs.vfat
    # Module loading
    insmod rmmod modprobe depmod
    # Kernel param modification
    sysctl
    # Init re-generation
    mkinitcpio dracut
    # Boot modification
    grub-install grub-mkconfig efibootmgr bootctl
)

for cmd in "${FORBIDDEN_CMDS[@]}"; do
    for dir in /sbin /usr/sbin /usr/bin /bin; do
        if [[ -f "${dir}/${cmd}" && ! -f "${dir}/${cmd}.bak" ]]; then
            mv "${dir}/${cmd}" "${dir}/${cmd}.bak"
            chattr +i "${dir}/${cmd}.bak" 2>/dev/null || true
        fi
    done

    # Create a dummy in /usr/bin (Arch default).
    # Intentionally NO chattr +i here – pacman needs to overwrite
    # these paths during package upgrades.  A post-transaction hook
    # (section 9) re-creates the dummies after every pacman operation.
    cat > "/usr/bin/${cmd}" <<'DUMMY'
#!/bin/bash
echo "Command disabled by Arch-Nemesis hardening."
exit 1
DUMMY
    chmod +x "/usr/bin/${cmd}"
done

# -------------------------------------------------------------------
# 3.  PROTECT IDENTITY FILES
# -------------------------------------------------------------------
echo "[3/12] Locking identity files …"
for f in /etc/passwd /etc/shadow /etc/group /etc/gshadow /etc/sudoers; do
    chattr +i "$f" 2>/dev/null || true
done
# Also protect sudoers.d
if [[ -d /etc/sudoers.d ]]; then
    for f in /etc/sudoers.d/*; do
        chattr +i "$f" 2>/dev/null || true
    done
fi

# -------------------------------------------------------------------
# 4.  PROTECT BOOTLOADER & KERNEL
# -------------------------------------------------------------------
echo "[4/12] Protecting boot files …"
# Lock grub config
for f in /boot/grub/grub.cfg /boot/grub/grubenv /boot/loader/loader.conf; do
    [[ -f "$f" ]] && chattr +i "$f" 2>/dev/null || true
done
# Lock kernel & initramfs images
for f in /boot/vmlinuz-* /boot/initramfs-*; do
    [[ -f "$f" ]] && chattr +i "$f" 2>/dev/null || true
done
# Lock the /boot directory entries list
[[ -d /boot/loader/entries ]] && chattr +i /boot/loader/entries/*.conf 2>/dev/null || true
# Lock EFI directory if present
[[ -d /boot/EFI ]] && find /boot/EFI -type f -exec chattr +i {} \; 2>/dev/null || true

# -------------------------------------------------------------------
# 5.  PROTECT CRITICAL SYSTEM FILES
# -------------------------------------------------------------------
echo "[5/12] Protecting critical config files …"
CRITICAL_FILES=(
    /etc/fstab
    /etc/crypttab
    /etc/hostname
    /etc/locale.conf
    /etc/vconsole.conf
    /etc/mkinitcpio.conf
    /etc/default/grub
    /etc/pacman.conf
    /etc/makepkg.conf
    /etc/systemd/system.conf
    /etc/systemd/user.conf
    /etc/systemd/logind.conf
    /etc/pam.d/system-login
    /etc/pam.d/su
    /etc/pam.d/sudo
)
for f in "${CRITICAL_FILES[@]}"; do
    [[ -f "$f" ]] && chattr +i "$f" 2>/dev/null || true
done

# -------------------------------------------------------------------
# 6.  PROTECT SYSTEMD UNIT MASKS
# -------------------------------------------------------------------
echo "[6/12] Protecting systemd mask symlinks …"
for target in poweroff reboot halt shutdown kexec ctrl-alt-del; do
    chattr +i "/etc/systemd/system/${target}.target" 2>/dev/null || true
done

# -------------------------------------------------------------------
# 7.  PREVENT FORK BOMBS & RESOURCE EXHAUSTION
# -------------------------------------------------------------------
echo "[7/12] Setting resource limits …"
chattr -i /etc/security/limits.conf 2>/dev/null || true
cat >> /etc/security/limits.conf <<'EOF'
# Arch-Nemesis: prevent fork bombs and resource abuse
*               hard    nproc           500
*               hard    nofile          8192
*               hard    memlock         1048576
EOF
# Make it immutable (already done in section 5, but be safe)
chattr +i /etc/security/limits.conf 2>/dev/null || true

# Systemd-level limits for user sessions
mkdir -p /etc/systemd/system/user-.slice.d
cat > /etc/systemd/system/user-.slice.d/50-arch-nemesis.conf <<'EOF'
[Slice]
TasksMax=400
MemoryMax=3G
CPUQuota=90%
EOF
chattr +i /etc/systemd/system/user-.slice.d/50-arch-nemesis.conf 2>/dev/null || true

# -------------------------------------------------------------------
# 8.  DISABLE DANGEROUS KERNEL MODULES
# -------------------------------------------------------------------
echo "[8/12] Blacklisting dangerous kernel modules …"
cat > /etc/modprobe.d/arch-nemesis-blacklist.conf <<'EOF'
# Prevent loading modules that could be used for attacks
install usb-storage /bin/true
install firewire-core /bin/true
install firewire-net /bin/true
install firewire-sbp2 /bin/true
install thunderbolt /bin/true
EOF
chattr +i /etc/modprobe.d/arch-nemesis-blacklist.conf 2>/dev/null || true

# -------------------------------------------------------------------
# 9.  PROTECT PACKAGE MANAGER (allow install, block sabotage)
# -------------------------------------------------------------------
echo "[9/12] Protecting package manager …"

# Lock pacman.conf to prevent adding malicious repos (pacman reads it fine)
chattr +i /etc/pacman.conf 2>/dev/null || true

mkdir -p /etc/pacman.d/hooks

# 9a. Prevent removing critical packages
cat > /etc/pacman.d/hooks/protect-critical.hook <<'EOF'
[Trigger]
Type = Package
Operation = Remove
Target = linux
Target = linux-lts
Target = base
Target = glibc
Target = bash
Target = systemd
Target = filesystem
Target = coreutils
Target = iptables
Target = iptables-nft

[Action]
Description = Blocking removal of critical packages
When = PreTransaction
Exec = /bin/false
EOF
chattr +i /etc/pacman.d/hooks/protect-critical.hook 2>/dev/null || true

# 9b. Post-transaction hook: re-create dummy binaries after every
#     install/upgrade so that pacman -Syu can overwrite them and we
#     immediately put them back.
cat > /usr/local/bin/arch-nemesis-reapply.sh <<'REAPPLY'
#!/bin/bash
FORBIDDEN="shutdown poweroff reboot halt passwd usermod useradd userdel groupmod groupadd groupdel chsh dd mkfs fdisk parted wipefs shred sgdisk gdisk cfdisk sfdisk mkswap mkfs.ext4 mkfs.btrfs mkfs.xfs mkfs.vfat insmod rmmod modprobe depmod sysctl mkinitcpio dracut grub-install grub-mkconfig efibootmgr bootctl"

for cmd in $FORBIDDEN; do
    target="/usr/bin/${cmd}"
    # If the file is missing OR is a real binary (not our dummy), replace it
    if [[ ! -f "$target" ]] || ! grep -q "Arch-Nemesis" "$target" 2>/dev/null; then
        cat > "$target" <<'DUMMY'
#!/bin/bash
echo "Command disabled by Arch-Nemesis hardening."
exit 1
DUMMY
        chmod +x "$target"
    fi
done
REAPPLY
chmod +x /usr/local/bin/arch-nemesis-reapply.sh
chattr +i /usr/local/bin/arch-nemesis-reapply.sh 2>/dev/null || true

cat > /etc/pacman.d/hooks/reapply-hardening.hook <<'EOF'
[Trigger]
Type = Package
Operation = Install
Operation = Upgrade
Target = *

[Action]
Description = Re-applying Arch-Nemesis binary protections …
When = PostTransaction
Exec = /usr/local/bin/arch-nemesis-reapply.sh
EOF
chattr +i /etc/pacman.d/hooks/reapply-hardening.hook 2>/dev/null || true

# -------------------------------------------------------------------
# 10. LOCK DOWN CRON / AT / TIMERS
# -------------------------------------------------------------------
echo "[10/12] Restricting scheduled tasks …"
# Only root can use cron/at
echo "root" > /etc/cron.allow 2>/dev/null || true
echo "root" > /etc/at.allow 2>/dev/null || true
chattr +i /etc/cron.allow 2>/dev/null || true
chattr +i /etc/at.allow 2>/dev/null || true

# -------------------------------------------------------------------
# 11. PROTECT THIS SCRIPT
# -------------------------------------------------------------------
echo "[11/12] Making hardening script immutable …"
SCRIPT_PATH="$(realpath "$0")"
chattr +i "$SCRIPT_PATH" 2>/dev/null || true

# -------------------------------------------------------------------
# 12. HIDE CHATTR (nuclear option)
# -------------------------------------------------------------------
echo "[12/12] Hiding chattr …"
SECRET_CHATTR="chattr_$(head -c 8 /dev/urandom | xxd -p)"
if [[ -f /usr/bin/chattr ]]; then
    mv /usr/bin/chattr "/usr/bin/${SECRET_CHATTR}"
    echo ""
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  IMPORTANT: Save this – the only way to undo is:   ║"
    echo "║  /usr/bin/${SECRET_CHATTR}                          "
    echo "╚══════════════════════════════════════════════════════╝"
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "  Hardening complete."
echo "  The VM is now resistant to chat-driven sabotage."
echo "═══════════════════════════════════════════════"
