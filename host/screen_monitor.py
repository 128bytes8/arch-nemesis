"""
Optional AI-powered screen monitor for Arch-Nemesis.

Takes periodic screenshots of the VM via ``virsh screenshot`` and runs
them through NudeNet to detect NSFW content.  When something is found
it force-closes the foreground window inside the VM.

Enable with ``--screen-monitor`` on the controller CLI.
Requires: ``pip install nudenet Pillow``
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time

log = logging.getLogger("archnemesis.screen")


class ScreenMonitor:
    def __init__(
        self,
        vm_name: str,
        virsh_uri: str = "qemu:///system",
        interval: float = 5.0,
        threshold: float = 0.45,
    ):
        self.vm_name = vm_name
        self.virsh_uri = virsh_uri
        self.interval = interval
        self.threshold = threshold
        self._running = False
        self._thread: threading.Thread | None = None
        self.detector = None
        self.enabled = False
        self.detections = 0

        try:
            from nudenet import NudeDetector  # type: ignore[import-untyped]
            self.detector = NudeDetector()
            self.enabled = True
            log.info("NudeNet loaded – screen monitoring active")
        except ImportError:
            log.warning(
                "nudenet not installed – screen monitoring disabled. "
                "Install with: pip install nudenet Pillow"
            )

    def _take_screenshot(self) -> str | None:
        """Capture the VM framebuffer to a temp PPM file."""
        fd, path = tempfile.mkstemp(suffix=".ppm")
        os.close(fd)
        result = subprocess.run(
            ["virsh", "-c", self.virsh_uri, "screenshot", self.vm_name, path],
            capture_output=True,
        )
        if result.returncode == 0 and os.path.getsize(path) > 0:
            return path
        os.unlink(path)
        return None

    @staticmethod
    def _ppm_to_png(ppm_path: str) -> str | None:
        """Convert PPM → PNG (NudeNet needs a standard image format)."""
        try:
            from PIL import Image  # type: ignore[import-untyped]
            png_path = ppm_path.rsplit(".", 1)[0] + ".png"
            Image.open(ppm_path).save(png_path)
            return png_path
        except Exception:
            return None

    def _is_nsfw(self, image_path: str) -> bool:
        if self.detector is None:
            return False
        try:
            results = self.detector.detect(image_path)
        except Exception as exc:
            log.debug("NudeNet inference error: %s", exc)
            return False

        nsfw_labels = {
            "FEMALE_BREAST_EXPOSED",
            "FEMALE_GENITALIA_EXPOSED",
            "MALE_GENITALIA_EXPOSED",
            "BUTTOCKS_EXPOSED",
            "ANUS_EXPOSED",
        }
        return any(
            r.get("class") in nsfw_labels and r.get("score", 0) >= self.threshold
            for r in results
        )

    def _nuke_foreground(self) -> None:
        """Send Ctrl+W then Alt+F4 to kill whatever is showing NSFW."""
        virsh = ["virsh", "-c", self.virsh_uri, "send-key", self.vm_name]
        subprocess.run(virsh + ["KEY_LEFTCTRL", "KEY_W"], capture_output=True)
        time.sleep(0.3)
        subprocess.run(virsh + ["KEY_LEFTALT", "KEY_F4"], capture_output=True)

    def _loop(self) -> None:
        while self._running:
            ppm = self._take_screenshot()
            if ppm:
                png = self._ppm_to_png(ppm)
                try:
                    target = png or ppm
                    if self._is_nsfw(target):
                        self.detections += 1
                        log.warning(
                            "NSFW DETECTED (count=%d) – closing foreground window",
                            self.detections,
                        )
                        self._nuke_foreground()
                finally:
                    if ppm and os.path.exists(ppm):
                        os.unlink(ppm)
                    if png and os.path.exists(png):
                        os.unlink(png)
            time.sleep(self.interval)

    def start(self) -> None:
        if not self.enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="screen-monitor")
        self._thread.start()
        log.info("Screen monitor started (interval=%ss, threshold=%.2f)", self.interval, self.threshold)

    def stop(self) -> None:
        self._running = False
