"""One external Chrome process and persistent profile for the fixed local account."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import time
from urllib.request import build_opener, ProxyHandler
from src.failure_guard import _FileLock

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "data" / "chrome-private_2"

def browser_for(account):
    config_file = ROOT / "data" / "account-browsers.json"
    config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    browser = config.get(account, "chrome")
    if browser not in ("chrome", "edge", "firefox", "pending"):
        raise ValueError("不支持的账号浏览器配置")
    return browser


def account_browser_ready(state_file):
    path = Path(state_file)
    if browser_for(path.stem) == "pending":
        return False
    pending_file = ROOT / "data" / "account-browser-pending.json"
    pending = json.loads(pending_file.read_text(encoding="utf-8")) if pending_file.exists() else {}
    if path.stem not in pending:
        return True
    return hashlib.sha256(path.read_bytes()).hexdigest() != pending[path.stem]


def profile_for(account="private_2"):
    if not account or Path(account).name != account or any(c in account for c in '/\\:') or account in ('.', '..'):
        raise ValueError("无效账号名称")
    overrides_file = ROOT / "data" / "chrome-profile-overrides.json"
    overrides = json.loads(overrides_file.read_text(encoding="utf-8")) if overrides_file.exists() else {}
    directory = overrides.get(account, "chrome-" + account)
    if not isinstance(directory, str) or not directory.startswith("chrome-") or Path(directory).name != directory or any(c in directory for c in '/\\:'):
        raise ValueError("无效 Chrome 配置目录")
    return ROOT / "data" / directory


def uses_shared_chrome(state_file):
    path = Path(state_file).resolve()
    return (os.getenv("LOCAL_SHARED_CHROME", "").lower() == "true"
            and path.parent == (ROOT / "state").resolve() and path.suffix == '.json')

def _endpoint(profile):
    try:
        lines = (profile / "DevToolsActivePort").read_text().splitlines()
        port = int(lines[0])
        if not 1 <= port <= 65535 or not lines[1].startswith("/devtools/browser/"):
            return None
        url = f"http://127.0.0.1:{port}"
        with build_opener(ProxyHandler({})).open(url + "/json/version", timeout=1) as r:
            data = json.load(r)
        if data.get("webSocketDebuggerUrl", "").endswith(lines[1]):
            return url
    except (OSError, ValueError, IndexError):
        pass
    return None

def ensure_shared_chrome(account="private_2"):
    selected_browser = browser_for(account)
    if selected_browser == "firefox":
        raise RuntimeError("Firefox 必须通过常驻 Firefox worker 连接，不能使用 Chrome CDP")
    if selected_browser == "pending":
        raise RuntimeError("请先为该账号指定浏览器")
    profile = profile_for(account)
    profile.mkdir(parents=True, exist_ok=True)
    with (profile / "startup.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0"); lock.flush()
        with _FileLock(lock):
            endpoint = _endpoint(profile)
            if endpoint:
                return endpoint
            suffix = "Microsoft/Edge/Application/msedge.exe" if selected_browser == "edge" else "Google/Chrome/Application/chrome.exe"
            candidates = [Path(os.environ.get(key, "")) / suffix
                          for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
            chrome = next((p for p in candidates if p.is_file()), None)
            if chrome is None:
                raise RuntimeError(f"未找到已安装的 {selected_browser}")
            subprocess.Popen([str(chrome), f"--user-data-dir={profile}",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            for _ in range(60):
                endpoint = _endpoint(profile)
                if endpoint:
                    return endpoint
                time.sleep(0.25)
            raise RuntimeError("专用 Chrome 未能连接；请关闭专用窗口后重试，不要关闭其他浏览器")

async def attach_shared_chrome(playwright, snapshot, account="private_2"):
    profile = profile_for(account)
    browser = await playwright.chromium.connect_over_cdp(ensure_shared_chrome(account))
    context = browser.contexts[0]
    # Only seed once. Subsequent connections must preserve the live verified session.
    marker = profile / "seeded.json"
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    try:
        seeded = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        seeded = {}
    if seeded.get('fingerprint') != fingerprint:
        from src.services.local_browser import storage_from_snapshot
        state = storage_from_snapshot(snapshot or {})
        await context.clear_cookies()
        await context.add_cookies(state["cookies"])
        page = context.pages[0] if context.pages else await context.new_page()
        for origin in state["origins"]:
            if origin.get("origin") != "https://www.goofish.com":
                continue
            await page.goto(origin["origin"], wait_until="domcontentloaded")
            await page.evaluate("items => items.forEach(x => localStorage.setItem(x.name, x.value))", origin.get("localStorage", []))
        marker.write_text(json.dumps({"account": account, "fingerprint": fingerprint}), encoding="utf-8")
    return browser, context
