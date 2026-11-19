"""Open the existing account for user-operated verification; no automatic challenge handling."""
import os,json
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parent
os.chdir(root)
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(root/'.browsers')
state_file=root/'state'/'personal.json'
if not state_file.exists():
 raise SystemExit('找不到已保存的 personal 登录态，请先运行 login-local.cmd。')
with sync_playwright() as p:
 browser=p.chromium.launch(headless=False,channel='chromium')
 context=browser.new_context(storage_state=str(state_file))
 page=context.new_page()
 try:
  page.goto('https://www.goofish.com/search?'+urlencode({'q':'aph仏英'}),wait_until='domcontentloaded',timeout=60000)
 except Exception:
  print('页面加载超时，请在浏览器中检查或手动刷新。')
 input('请自行完成闲鱼验证，确认搜索页显示商品后，回到本窗口按 Enter 保存。取消请按 Ctrl+C。\n')
 state=context.storage_state()
 if not any(c.get('name')=='cookie2' and c.get('value') for c in state['cookies']):
  raise SystemExit('未发现登录会话，没有覆盖原文件。')
 pending=state_file.with_suffix('.pending.json')
 pending.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
 pending.replace(state_file)
 print('已保存更新后的登录态。请告诉我，我会检查是否恢复。')
 browser.close()
