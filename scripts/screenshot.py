"""Full-page screenshot of a local web page with headless Chrome (no window, muted).

Uses the Chrome DevTools protocol so it can wait until the page has actually rendered
(Streamlit fills the page over a websocket after load, which --screenshot does not wait for).

usage: python scripts/screenshot.py URL OUT.png [--wait-text TEXT] [--width 1400] [--timeout 60]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

import websockets

CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]


class Cdp:
    def __init__(self, ws):
        self.ws, self.next_id = ws, 0

    async def call(self, method: str, **params):
        self.next_id += 1
        msg_id = self.next_id
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


async def capture(port: int, url: str, out: str, wait_text: str | None, width: int, timeout: float):
    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    page = next(t for t in targets if t["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        cdp = Cdp(ws)
        await cdp.call(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=1000,
            deviceScaleFactor=1,
            mobile=False,
        )
        await cdp.call("Page.enable")
        await cdp.call("Page.navigate", url=url)
        deadline = time.monotonic() + timeout
        check = "document.body ? document.body.innerText : ''"
        while True:
            text = (await cdp.call("Runtime.evaluate", expression=check))["result"].get("value", "")
            busy = (
                await cdp.call(
                    "Runtime.evaluate",
                    expression=("!!document.querySelector('[data-testid=\"stStatusWidget\"]')"),
                )
            )["result"].get("value", False)
            if (wait_text is None or wait_text in text) and not busy and len(text) > 50:
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"page never showed {wait_text!r}")
            await asyncio.sleep(1)
        await asyncio.sleep(3)  # let charts finish drawing
        # Streamlit scrolls inside its own container; size the viewport to the full content.
        height = (
            await cdp.call(
                "Runtime.evaluate",
                expression=(
                    "Math.max(document.body.scrollHeight, ...Array.from(document.querySelectorAll("
                    '\'[data-testid="stMain"], section.main, [data-testid="stAppViewContainer"]\'))'
                    ".map(e => e.scrollHeight))"
                ),
            )
        )["result"]["value"]
        await cdp.call(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=int(height) + 40,
            deviceScaleFactor=1,
            mobile=False,
        )
        await asyncio.sleep(2)
        shot = await cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
        with open(out, "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("out")
    p.add_argument("--wait-text")
    p.add_argument("--width", type=int, default=1400)
    p.add_argument("--timeout", type=float, default=60)
    args = p.parse_args()
    chrome = next(c for c in CHROME_CANDIDATES if c and os.path.exists(c))
    port = 9333
    with tempfile.TemporaryDirectory() as profile:
        proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                f"--remote-debugging-port={port}",
                "--disable-gpu",
                "--mute-audio",
                "--no-first-run",
                "--no-default-browser-check",
                "--hide-scrollbars",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
                    break
                except OSError:
                    time.sleep(0.2)
            asyncio.run(capture(port, args.url, args.out, args.wait_text, args.width, args.timeout))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
