"""User-operated login; save the session locally without printing cookies."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent
os.chdir(root)
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(root / '.browsers')
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel='chromium')
    context = browser.new_context()
    page = context.new_page()
    page.goto('https://www.goofish.com/', wait_until='domcontentloaded')
    input('请在浏览器中自行登录闲鱼，确认已登录后回到这里按 Enter 保存；取消请按 Ctrl+C。\n')
    state = context.storage_state()
    if not any(c.get('name') == 'cookie2' and c.get('value') for c in state['cookies']):
        raise SystemExit('未发现登录会话 cookie2，没有保存。请重新登录。')
    (root / 'state').mkdir(exist_ok=True)
    context.storage_state(path=str(root / 'state' / 'personal.json'))
    browser.close()
    print('已保存到本机 state/personal.json。请在任务中绑定 personal 账号；实际搜索可用性仍需测试。')
