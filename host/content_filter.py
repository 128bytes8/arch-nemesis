"""
Multi-layered NSFW and dangerous-content filter for Arch-Nemesis.

Layers provided by this module (host-side, text-based):
  1. NSFW keyword detection  (word-boundary + leet-speak normalisation)
  2. Blocked-domain / URL detection  (substring + full-domain matching)
  3. Dangerous system-command detection  (regex patterns)

Network-level layers (DNS, hosts-file, firewall) are handled by
guest/setup_content_filter.sh and run *inside* the VM.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
#  NSFW KEYWORD LISTS
# ═══════════════════════════════════════════════════════════════════════
# Single tokens – matched with \\b word boundaries (case-insensitive).
# Sorted alphabetically within each category for maintainability.

_NSFW_WORDS: set[str] = {
    # -- Pornography / adult-content type labels --
    "erotica", "erotic", "nsfw", "porn", "pornhub",
    "porno", "pornographic", "pornography", "pornstar",
    "r18", "smut", "softcore", "hardcore", "xrated", "xxx",

    # -- Hentai / anime NSFW --
    "ahegao", "doujin", "doujinshi", "ecchi", "futanari",
    "hentai", "oppai", "r34", "rule34", "yaoi", "yuri",

    # -- Exploitation / illegal (CRITICAL) --
    "childporn", "csam", "jailbait", "loli", "lolicon",
    "pedo", "pedophile", "pedophilia", "shota", "shotacon",

    # -- Sexual acts --
    "blowjob", "bukkake", "creampie", "cumshot",
    "cunnilingus", "deepthroat", "ejaculate", "ejaculation",
    "fap", "fapping", "fellatio", "footjob", "foursome",
    "gangbang", "handjob", "masturbate", "masturbation",
    "orgasm", "orgy", "rimjob", "threesome", "titjob",

    # -- Body parts (sexual context) --
    "boner", "boobies", "boobs", "clitoris", "cock",
    "cunt", "erection", "genitalia", "genitals",
    "nipple", "nipples", "penis", "pussy", "tits",
    "vagina", "vulva",

    # -- Fetish / kink --
    "ballgag", "bdsm", "bondage", "dominatrix", "femdom",
    "fisting", "pegging", "sadomasochism", "shibari",

    # -- Adult industry --
    "camboy", "camgirl", "escort", "hooker", "lapdance",
    "milf", "prostitute", "prostitution", "slut",
    "stripper", "striptease", "whore",

    # -- Nudity --
    "bottomless", "downblouse", "nudes", "nude", "nudity",
    "naked", "topless", "upskirt",

    # -- Extreme / gore --
    "bestiality", "gore", "gory", "necrophilia",
    "snuff", "zoophilia",

    # -- Well-known NSFW site names (as typed keywords) --
    "bangbros", "babes", "brazzers", "chaturbate", "camsoda",
    "eporner", "fakehub", "fansly", "gelbooru", "hanime",
    "hentaihaven", "imagefap", "livejasmin", "manyvids",
    "motherless", "myfreecams", "nhentai", "onlyfans",
    "porndig", "pornmd", "pornone", "pornpics", "porntube",
    "realitykings", "redtube", "spankbang", "stripchat",
    "teamskeet", "thumbzilla", "tube8", "tushy", "txxx",
    "xhamster", "xnxx", "xvideos", "youporn",
}

# Multi-word phrases – matched as substrings (no word-boundary needed).
_NSFW_PHRASES: set[str] = {
    "anal sex", "child porn", "leaked nude", "leaked nudes",
    "onlyfans leak", "oral sex", "sex tape", "sex video",
    "tentacle porn",
}

# ═══════════════════════════════════════════════════════════════════════
#  BLOCKED DOMAINS  (used for URL detection in typed text)
# ═══════════════════════════════════════════════════════════════════════
# DNS/hosts-file blocking inside the VM is the primary network defence;
# this list is a *secondary* layer that prevents the keystrokes from
# even reaching the VM.

_BLOCKED_DOMAINS: set[str] = {
    # ── Tube / streaming ──
    "pornhub.com", "xvideos.com", "xnxx.com", "xhamster.com",
    "redtube.com", "youporn.com", "tube8.com", "spankbang.com",
    "eporner.com", "ixxx.com", "porntrex.com", "txxx.com",
    "beeg.com", "pornmd.com", "thumbzilla.com", "porndig.com",
    "hqporner.com", "fuq.com", "pornone.com", "porntube.com",
    "youjizz.com", "jizzbunker.com", "tnaflix.com", "empflix.com",
    "pornrabbit.com", "cliphunter.com", "xbabe.com", "xxxbunker.com",
    "nudevista.com", "porn.com", "sex.com", "drtuber.com",
    "sunporno.com", "nuvid.com", "gotporn.com", "anyporn.com",
    "hdzog.com", "pornflip.com", "pornhd.com", "pornpics.com",
    "porn300.com", "porngo.com", "xfreehd.com", "fapvid.com",
    "yobt.com", "lobstertube.com", "tubegalore.com", "pornhat.com",
    "cumlouder.com", "perfectgirls.net", "ashemaletube.com",
    "3movs.com", "sexvid.xxx", "tubev.sex", "pornoxo.com",
    "4tube.com", "vporn.com", "zbporn.com", "proporn.com",
    "letsjerk.tv", "fux.com", "pornzog.com", "tubedupe.com",
    "megatube.xxx", "pornid.xxx", "pornoxo.com", "sextube.com",
    "slutload.com", "extremetube.com", "keezmovies.com",
    "pornerbros.com", "hartporn.com", "xfantasy.com",

    # ── Live cam sites ──
    "chaturbate.com", "livejasmin.com", "stripchat.com",
    "cam4.com", "camsoda.com", "myfreecams.com", "bongacams.com",
    "flirt4free.com", "streamate.com", "imlive.com", "camster.com",
    "sakuralive.com", "camonster.com", "camfuze.com",
    "cam4.com", "xcams.com", "xlovecam.com",

    # ── Premium / studio ──
    "brazzers.com", "realitykings.com", "bangbros.com", "mofos.com",
    "naughtyamerica.com", "babes.com", "tushy.com", "blacked.com",
    "vixen.com", "wicked.com", "digitalplayground.com", "fakehub.com",
    "teamskeet.com", "metart.com", "twistys.com", "penthouse.com",
    "hustler.com", "vivid.com", "kink.com", "evilangel.com",
    "adulttime.com", "private.com", "dorcelclub.com", "legalporno.com",
    "julesjordan.com", "girlsway.com", "puretaboo.com",

    # ── Fan / creator platforms ──
    "onlyfans.com", "fansly.com", "manyvids.com", "clips4sale.com",
    "loyalfans.com", "justfor.fans", "modelhub.com",
    "pornstarplatinum.com", "suicidegirls.com", "ismygirl.com",

    # ── Hentai / anime NSFW ──
    "nhentai.net", "hanime.tv", "hentaihaven.xxx", "rule34.xxx",
    "rule34.paheal.net", "e621.net", "gelbooru.com",
    "danbooru.donmai.us", "sankakucomplex.com", "exhentai.org",
    "e-hentai.org", "hitomi.la", "tsumino.com", "hentai2read.com",
    "simply-hentai.com", "hentaihere.com", "fakku.net", "doujins.com",
    "myreadingmanga.info", "hentaidude.com", "hentaiworld.tv",
    "hentaimama.io", "hentaistream.com", "muchohentai.com",
    "animeidhentai.com", "nhencloud.com", "hentaigasm.com",
    "pururin.to", "luscious.net", "8muses.com",

    # ── Image hosts / NSFW boards ──
    "imagefap.com", "motherless.com", "4chan.org", "8kun.top",

    # ── Gore / shock ──
    "bestgore.fun", "theync.com", "crazyshit.com", "kaotic.com",
    "efukt.com", "heavy-r.com",

    # ── Escort / hookup ──
    "adultfriendfinder.com", "ashleymadison.com", "fetlife.com",
    "eros.com", "tryst.link", "slixa.com", "skipthegames.com",
    "adultlook.com", "listcrawler.com", "megapersonals.com",
    "bedpage.com",

    # ── NSFW subreddits are handled by DNS; block reddit entirely
    #    for a controlled-VM stream (optional – remove if too strict)
    "reddit.com", "redd.it",

    # ── Adult stores / aggregators ──
    "adameve.com", "adultempire.com", "aebn.com", "hotmovies.com",

    # ── NSFW art communities ──
    "furaffinity.net", "inkbunny.net", "e926.net",
    "newgrounds.com",
}

# URL shorteners (can redirect to anything, bypassing domain checks)
_URL_SHORTENERS: set[str] = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly",
    "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at",
    "tiny.cc", "lnkd.in", "rb.gy", "clck.ru", "v.gd",
    "qr.ae", "adf.ly", "bc.vc", "soo.gd", "s.coop",
}

# Substrings that make ANY domain suspicious (matched against the
# registered domain name, not the full URL path).
_NSFW_DOMAIN_KEYWORDS: set[str] = {
    "porn", "xxx", "hentai", "nsfw", "nude", "naked",
    "adult", "erotic", "fetish", "escort", "camgirl",
    "sexvid", "xvideo", "xnxx", "xhamster", "redtube",
    "youporn", "brazzers", "chaturbate", "onlyfans",
    "fansly", "nhentai", "r34", "rule34", "livejasmin",
    "stripchat", "loli", "shota",
}

# ═══════════════════════════════════════════════════════════════════════
#  DANGEROUS SYSTEM COMMANDS  (regex patterns, case-insensitive)
# ═══════════════════════════════════════════════════════════════════════
_DANGEROUS_PATTERNS: list[str] = [
    # Destructive disk/filesystem ops
    r'\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)?/',
    r'\bdd\s+.*of\s*=\s*/dev/',
    r'\bmkfs\b',
    r'\bfdisk\b',
    r'\bparted\b',
    r'\bwipefs\b',
    r'\bshred\b',
    r'>\s*/dev/sd[a-z]',
    r'>\s*/dev/nvme',
    r'>\s*/dev/vd[a-z]',

    # Fork bomb patterns
    r':\(\)\s*\{',
    r'\.\(\)\s*\{',

    # NOTE: blanket sudo/su blocks are intentionally absent.
    # Package management (pacman -S, yay, paru) requires sudo.
    # Individual dangerous commands (rm, dd, mkfs …) are already
    # caught by their own patterns regardless of a sudo prefix,
    # and the VM hardening script (chattr +i on configs, masked
    # systemd targets, dummy binaries) is the real last-resort
    # defence against privilege abuse.

    # Service / init disruption
    r'\bsystemctl\s+(disable|mask|stop|kill)\s',
    r'\bkill\s+-9?\s*1\b',
    r'\bkillall\b',
    r'\bkill\s+-(?:KILL|STOP|TERM)\s',

    # Package manager removal of critical packages
    r'\bpacman\s+-[A-Za-z]*R',
    r'\byay\s+-[A-Za-z]*R',
    r'\bparu\s+-[A-Za-z]*R',

    # Network / DNS sabotage
    r'\bresolv\.conf\b',
    r'/etc/hosts\b',
    r'\biptables\b',
    r'\bnftables\b',
    r'\bnft\s',
    r'\bip\s+route\b',
    r'\bip\s+addr\b',
    r'\bnmcli\b',
    r'\bnetworkctl\b',
    r'\bresolvectl\b',

    # Filesystem / attribute tampering
    r'\bchattr\b',
    r'\bchmod\s+[0-7]{3,4}\s+/',
    r'\bchown\s+.*\s+/',

    # Kernel / module tampering
    r'\binsmod\b',
    r'\brmmod\b',
    r'\bmodprobe\b',
    r'\bsysctl\b',
    r'\bmkinitcpio\b',
    r'\bdracut\b',

    # Boot tampering
    r'\bgrub-',
    r'\befibootmgr\b',

    # Mount operations
    r'\bmount\b',
    r'\bumount\b',
    r'\bswapoff\b',

    # Pipe-to-shell attacks
    r'\bcurl\b.*\|\s*(ba)?sh',
    r'\bwget\b.*\|\s*(ba)?sh',
]

# ═══════════════════════════════════════════════════════════════════════
#  CONTENT FILTER CLASS
# ═══════════════════════════════════════════════════════════════════════

class ContentFilter:
    """
    Text-level content gate that runs on the *host* before keystrokes
    are forwarded to the VM.

    Usage::

        cf = ContentFilter()
        ok, reason = cf.filter_type_command("some user text")
        if not ok:
            log.warning("Blocked: %s", reason)
    """

    def __init__(
        self,
        extra_keywords_file: str | None = None,
        extra_domains_file: str | None = None,
    ):
        self.nsfw_words = set(_NSFW_WORDS)
        self.nsfw_phrases = set(_NSFW_PHRASES)
        self.blocked_domains = set(_BLOCKED_DOMAINS)
        self.url_shorteners = set(_URL_SHORTENERS)
        self.nsfw_domain_keywords = set(_NSFW_DOMAIN_KEYWORDS)

        if extra_keywords_file:
            self._load_lines(extra_keywords_file, self.nsfw_words)
        if extra_domains_file:
            self._load_lines(extra_domains_file, self.blocked_domains)

        # Pre-compile a single alternation regex for speed
        escaped = sorted(
            (re.escape(w) for w in self.nsfw_words),
            key=len, reverse=True,
        )
        self._word_re = re.compile(
            r'\b(?:' + '|'.join(escaped) + r')\b',
            re.IGNORECASE,
        )
        self._phrase_re = re.compile(
            '|'.join(re.escape(p) for p in self.nsfw_phrases),
            re.IGNORECASE,
        )
        self._url_re = re.compile(
            r'(?:https?://)?(?:www\.)?'
            r'([a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z0-9][-a-zA-Z0-9]*)+)',
        )
        self._dangerous_res = [
            re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS
        ]

    # ── public API ────────────────────────────────────────────────────

    def filter_type_command(self, text: str) -> tuple[bool, str | None]:
        """Return ``(allowed, reason)`` for a ``!type`` payload."""
        ok, reason = self._check_nsfw(text)
        if not ok:
            return False, reason
        ok, reason = self._check_urls(text)
        if not ok:
            return False, reason
        ok, reason = self._check_dangerous(text)
        if not ok:
            return False, reason
        return True, None

    def filter_key_command(self, key: str) -> tuple[bool, str | None]:
        """Return ``(allowed, reason)`` for a ``!key`` payload."""
        # Keys are fine – system hardening handles reboot/shutdown combos
        return True, None

    # ── internals ─────────────────────────────────────────────────────

    @staticmethod
    def _load_lines(path: str, target: set[str]) -> None:
        p = Path(path)
        if not p.is_file():
            return
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                target.add(line.lower())

    @staticmethod
    def _normalize(text: str) -> str:
        """Collapse leet-speak and separator obfuscation."""
        leet = str.maketrans('013457@$', 'oieastas')
        text = text.lower().translate(leet)
        text = re.sub(r'(?<=\w)[.\-_*]+(?=\w)', '', text)
        return text

    def _check_nsfw(self, text: str) -> tuple[bool, str | None]:
        for version in (text, self._normalize(text)):
            m = self._word_re.search(version)
            if m:
                return False, f"NSFW keyword: {m.group()}"
            m = self._phrase_re.search(version)
            if m:
                return False, f"NSFW phrase detected"
        return True, None

    def _check_urls(self, text: str) -> tuple[bool, str | None]:
        for match in self._url_re.finditer(text):
            domain = match.group(1).lower()

            # Exact domain match (or any parent domain)
            parts = domain.split('.')
            for i in range(len(parts) - 1):
                candidate = '.'.join(parts[i:])
                if candidate in self.blocked_domains:
                    return False, f"Blocked domain: {candidate}"

            # URL shortener
            for shortener in self.url_shorteners:
                if shortener in domain:
                    return False, f"URL shortener blocked: {shortener}"

            # Suspicious domain-name substring
            domain_name = parts[0]
            for kw in self.nsfw_domain_keywords:
                if kw in domain_name:
                    return False, f"Suspicious domain: {domain} (contains '{kw}')"

        return True, None

    def _check_dangerous(self, text: str) -> tuple[bool, str | None]:
        for pattern in self._dangerous_res:
            if pattern.search(text):
                return False, "Dangerous system command blocked"
        return True, None
