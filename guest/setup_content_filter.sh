#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  Arch-Nemesis  –  Network-Level NSFW Content Filter
# ═══════════════════════════════════════════════════════════════════════
#  Run ONCE inside the guest VM as root (AFTER harden_vm.sh).
#
#  Layers applied:
#    1. DNS → libvirt gateway (which forwards to Mullvad's adult-blocking DNS)
#    2. /etc/hosts → massive NSFW domain blocklist (downloaded)
#    3. iptables → force all DNS through gateway only
#    4. Block DNS-over-TLS (port 853)
#    5. Block common VPN/proxy/Tor ports
#    6. Block known DNS-over-HTTPS domains (in hosts file)
#    7. Lock all configs immutable
#
#  Usage:   sudo bash setup_content_filter.sh
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root."
    exit 1
fi

echo "═══════════════════════════════════════════════"
echo "  Arch-Nemesis Content Filter Setup"
echo "═══════════════════════════════════════════════"
echo ""

# Auto-detect chattr (harden_vm.sh renames it to a secret name)
CHATTR="chattr"
if ! command -v chattr &>/dev/null; then
    CHATTR=$(find /usr/bin -maxdepth 1 -name 'chattr_*' -type f 2>/dev/null | head -1)
    if [[ -z "$CHATTR" ]]; then
        echo "WARNING: chattr not found. File immutability will be skipped."
        CHATTR="true"  # no-op fallback
    else
        echo "Found renamed chattr: ${CHATTR}"
    fi
fi

# Gateway DNS (libvirt's dnsmasq on the host, forwarding to Mullvad's
# adult-content-blocking DNS).  This avoids Mullvad's DNS-leak firewall
# rules which reject all port-53 traffic to non-Mullvad servers.
GATEWAY_DNS="192.168.122.1"

# -------------------------------------------------------------------
# 1.  CONFIGURE FILTERED DNS
# -------------------------------------------------------------------
echo "[1/7] Setting DNS to libvirt gateway (Mullvad adult-blocking upstream) …"

# Remove immutable flag if it exists from a previous run
$CHATTR -i /etc/resolv.conf 2>/dev/null || true

cat > /etc/resolv.conf <<EOF
# Arch-Nemesis: use libvirt gateway DNS (Mullvad adult-content-blocking upstream)
nameserver ${GATEWAY_DNS}
EOF

# If systemd-resolved is active, configure it too
if systemctl is-active systemd-resolved &>/dev/null; then
    mkdir -p /etc/systemd/resolved.conf.d
    $CHATTR -i /etc/systemd/resolved.conf.d/arch-nemesis.conf 2>/dev/null || true
    cat > /etc/systemd/resolved.conf.d/arch-nemesis.conf <<EOF
[Resolve]
DNS=${GATEWAY_DNS}
FallbackDNS=
DNSOverTLS=no
DNSSEC=no
EOF
    $CHATTR +i /etc/systemd/resolved.conf.d/arch-nemesis.conf 2>/dev/null || true
    systemctl restart systemd-resolved 2>/dev/null || true
fi

# If NetworkManager is active, prevent it from overwriting resolv.conf
if systemctl is-active NetworkManager &>/dev/null; then
    mkdir -p /etc/NetworkManager/conf.d
    $CHATTR -i /etc/NetworkManager/conf.d/arch-nemesis-dns.conf 2>/dev/null || true
    cat > /etc/NetworkManager/conf.d/arch-nemesis-dns.conf <<EOF
[main]
dns=none
EOF
    $CHATTR +i /etc/NetworkManager/conf.d/arch-nemesis-dns.conf 2>/dev/null || true
fi

# Lock resolv.conf
$CHATTR +i /etc/resolv.conf

echo "    DNS set to ${GATEWAY_DNS} (gateway)"

# -------------------------------------------------------------------
# 2.  DOWNLOAD NSFW HOSTS BLOCKLIST
# -------------------------------------------------------------------
echo "[2/7] Downloading NSFW domain blocklists …"

HOSTS_TEMP=$(mktemp)
HOSTS_COMBINED=$(mktemp)

# Start with current localhost entries
cat > "$HOSTS_COMBINED" <<'EOF'
# Arch-Nemesis NSFW Blocklist
# Do not edit – managed by setup_content_filter.sh
127.0.0.1   localhost
::1         localhost

EOF

# Download StevenBlack porn extension
echo "    Fetching StevenBlack/hosts (porn)…"
curl -fsSL "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn-only/hosts" \
    -o "$HOSTS_TEMP" 2>/dev/null && {
    grep '^0\.0\.0\.0' "$HOSTS_TEMP" >> "$HOSTS_COMBINED" || true
    echo "    ✓ StevenBlack porn list loaded"
} || echo "    ✗ StevenBlack download failed (continuing)"

# Download oisd NSFW list
echo "    Fetching oisd.nl NSFW list…"
curl -fsSL "https://nsfw.oisd.nl/" \
    -o "$HOSTS_TEMP" 2>/dev/null && {
    grep '^0\.0\.0\.0\|^127\.0\.0\.1' "$HOSTS_TEMP" >> "$HOSTS_COMBINED" || true
    echo "    ✓ oisd NSFW list loaded"
} || echo "    ✗ oisd download failed (continuing)"

# Download UT1 adult category
echo "    Fetching UT1 Toulouse adult list…"
curl -fsSL "https://dsi.ut-capitole.fr/blacklists/download/adult.tar.gz" \
    -o /tmp/ut1-adult.tar.gz 2>/dev/null && {
    tar -xzf /tmp/ut1-adult.tar.gz -C /tmp/ 2>/dev/null || true
    if [[ -f /tmp/adult/domains ]]; then
        while IFS= read -r domain; do
            [[ -n "$domain" && ! "$domain" =~ ^# ]] && echo "0.0.0.0 ${domain}" >> "$HOSTS_COMBINED"
        done < /tmp/adult/domains
        echo "    ✓ UT1 adult list loaded"
    fi
    rm -rf /tmp/ut1-adult.tar.gz /tmp/adult
} || echo "    ✗ UT1 download failed (continuing)"

# Block DNS-over-HTTPS provider domains (prevents DoH bypass)
cat >> "$HOSTS_COMBINED" <<'EOF'

# Block DoH providers to prevent DNS filter bypass
0.0.0.0 dns.google
0.0.0.0 dns.google.com
0.0.0.0 dns64.dns.google
0.0.0.0 cloudflare-dns.com
0.0.0.0 one.one.one.one
0.0.0.0 1dot1dot1dot1.cloudflare-dns.com
0.0.0.0 dns.cloudflare.com
0.0.0.0 doh.opendns.com
0.0.0.0 dns.quad9.net
0.0.0.0 doh.cleanbrowsing.org
0.0.0.0 mozilla.cloudflare-dns.com
0.0.0.0 dns.nextdns.io
0.0.0.0 doh.dns.sb
0.0.0.0 dns.adguard.com
0.0.0.0 doh.mullvad.net
0.0.0.0 dns.controld.com
0.0.0.0 freedns.controld.com

# Block URL shorteners (can bypass domain filtering)
0.0.0.0 bit.ly
0.0.0.0 tinyurl.com
0.0.0.0 t.co
0.0.0.0 goo.gl
0.0.0.0 ow.ly
0.0.0.0 is.gd
0.0.0.0 buff.ly
0.0.0.0 rebrand.ly
0.0.0.0 cutt.ly
0.0.0.0 shorturl.at
0.0.0.0 tiny.cc
0.0.0.0 rb.gy
0.0.0.0 clck.ru
0.0.0.0 v.gd
0.0.0.0 adf.ly
0.0.0.0 bc.vc

# Block VPN / proxy web services
0.0.0.0 hide.me
0.0.0.0 hidemy.name
0.0.0.0 www.hidemyass.com
0.0.0.0 kproxy.com
0.0.0.0 proxysite.com
0.0.0.0 www.proxysite.com
0.0.0.0 free-proxy.cz
0.0.0.0 www.croxyproxy.com
0.0.0.0 croxyproxy.com
0.0.0.0 www.blockaway.net
0.0.0.0 www4.torproject.org
0.0.0.0 www.torproject.org
EOF

# De-duplicate and install
TOTAL_BEFORE=$(wc -l < "$HOSTS_COMBINED")
sort -u "$HOSTS_COMBINED" > /tmp/hosts_deduped
TOTAL_AFTER=$(wc -l < /tmp/hosts_deduped)

# Unlock hosts file if locked from a previous run
$CHATTR -i /etc/hosts 2>/dev/null || true
cp /tmp/hosts_deduped /etc/hosts

# Lock it
$CHATTR +i /etc/hosts

echo "    Installed ${TOTAL_AFTER} entries in /etc/hosts"
rm -f "$HOSTS_TEMP" "$HOSTS_COMBINED" /tmp/hosts_deduped

# -------------------------------------------------------------------
# 3.  FIREWALL: FORCE DNS THROUGH FILTERED RESOLVER
# -------------------------------------------------------------------
echo "[3/7] Configuring iptables firewall …"

# Flush existing custom rules (keep defaults)
iptables -F OUTPUT 2>/dev/null || true

# Allow loopback
iptables -A OUTPUT -o lo -j ACCEPT

# Allow established connections
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow DNS ONLY to our gateway resolver
iptables -A OUTPUT -p udp --dport 53 -d ${GATEWAY_DNS} -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -d ${GATEWAY_DNS} -j ACCEPT

# Block ALL other DNS (prevents resolver bypass)
iptables -A OUTPUT -p udp --dport 53 -j DROP
iptables -A OUTPUT -p tcp --dport 53 -j DROP

# Block DNS-over-TLS (port 853)
iptables -A OUTPUT -p tcp --dport 853 -j DROP

# Block common VPN ports
iptables -A OUTPUT -p udp --dport 1194 -j DROP   # OpenVPN
iptables -A OUTPUT -p tcp --dport 1194 -j DROP
iptables -A OUTPUT -p udp --dport 51820 -j DROP  # WireGuard
iptables -A OUTPUT -p tcp --dport 1723 -j DROP   # PPTP
iptables -A OUTPUT -p tcp --dport 443 -d 198.51.100.0/24 -j DROP  # example: known VPN ranges
iptables -A OUTPUT -p 47 -j DROP                  # GRE (PPTP tunnelling)

# Block Tor
iptables -A OUTPUT -p tcp --dport 9001 -j DROP
iptables -A OUTPUT -p tcp --dport 9030 -j DROP
iptables -A OUTPUT -p tcp --dport 9050 -j DROP
iptables -A OUTPUT -p tcp --dport 9051 -j DROP
iptables -A OUTPUT -p tcp --dport 9150 -j DROP

# Allow everything else (HTTP, HTTPS, etc. – DNS filtering handles the rest)
iptables -A OUTPUT -j ACCEPT

echo "    iptables rules installed"

# -------------------------------------------------------------------
# 4.  SAME FOR IPv6
# -------------------------------------------------------------------
echo "[4/7] Configuring ip6tables …"
ip6tables -F OUTPUT 2>/dev/null || true
ip6tables -A OUTPUT -o lo -j ACCEPT
ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
# Block all IPv6 DNS (our filtered DNS is IPv4-only)
ip6tables -A OUTPUT -p udp --dport 53 -j DROP
ip6tables -A OUTPUT -p tcp --dport 53 -j DROP
ip6tables -A OUTPUT -p tcp --dport 853 -j DROP
ip6tables -A OUTPUT -j ACCEPT
echo "    ip6tables rules installed"

# -------------------------------------------------------------------
# 5.  PERSIST FIREWALL RULES
# -------------------------------------------------------------------
echo "[5/7] Persisting firewall rules …"

# Save rules
mkdir -p /etc/iptables
iptables-save > /etc/iptables/iptables.rules
ip6tables-save > /etc/iptables/ip6tables.rules

# Enable iptables service to load on boot
systemctl enable iptables.service 2>/dev/null || true
systemctl enable ip6tables.service 2>/dev/null || true

# Lock the rule files
$CHATTR +i /etc/iptables/iptables.rules 2>/dev/null || true
$CHATTR +i /etc/iptables/ip6tables.rules 2>/dev/null || true

echo "    Firewall rules persisted"

# -------------------------------------------------------------------
# 6.  CONFIGURE BROWSER SAFE-SEARCH (enforcement via DNS)
# -------------------------------------------------------------------
echo "[6/7] Enforcing SafeSearch via hosts entries …"

# CleanBrowsing already enforces SafeSearch on Google, Bing, YouTube
# via DNS.  As belt-and-suspenders, force Google/YouTube SafeSearch
# by mapping to the restricted IPs.
$CHATTR -i /etc/hosts 2>/dev/null || true
cat >> /etc/hosts <<'EOF'

# Force Google SafeSearch
216.239.38.120 www.google.com
216.239.38.120 google.com
216.239.38.120 www.google.co.uk
216.239.38.120 www.google.ca
216.239.38.120 www.google.com.au

# Force YouTube Restricted Mode
216.239.38.120 www.youtube.com
216.239.38.120 m.youtube.com
216.239.38.120 youtube.com
216.239.38.120 youtubei.googleapis.com

# Force Bing SafeSearch
204.79.197.220 www.bing.com
204.79.197.220 bing.com

# Force DuckDuckGo SafeSearch
0.0.0.0 duckduckgo.com
0.0.0.0 www.duckduckgo.com
EOF
$CHATTR +i /etc/hosts 2>/dev/null || true

echo "    SafeSearch enforcement added"

# -------------------------------------------------------------------
# 7.  LOCK EVERYTHING DOWN
# -------------------------------------------------------------------
echo "[7/7] Final lockdown …"

# Protect this script
SCRIPT_PATH="$(realpath "$0")"
$CHATTR +i "$SCRIPT_PATH" 2>/dev/null || true

# Protect the network config files we created
$CHATTR +i /etc/resolv.conf 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════"
echo "  Content filter setup complete."
echo ""
echo "  Defence layers active:"
echo "    ✓ DNS:       Gateway → Mullvad (adult-content-blocking)"
echo "    ✓ Hosts:     NSFW domain blocklist installed"
echo "    ✓ Firewall:  DNS bypass prevention"
echo "    ✓ SafeSearch: Google/YouTube/Bing forced"
echo ""
echo "  IMPORTANT: On the HOST, run:"
echo "    mullvad dns set default --block-adult-content --block-malware"
echo ""
echo "  Test:  nslookup pornhub.com  (should NXDOMAIN or 0.0.0.0)"
echo "═══════════════════════════════════════════════"
