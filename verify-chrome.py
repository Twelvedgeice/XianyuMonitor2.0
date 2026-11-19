"""User-operated Chrome recovery; only save a successfully verified search session."""
import os,json,shutil,argparse,asyncio
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode
from playwright.async_api import async_playwright
from src.services.shared_chrome import attach_shared_chrome, browser_for
from src.services.firefox_runtime import worker_client
from src.services.local_browser import desktop_options,storage_from_snapshot
from src.services.new_listing_policy import validate_search_response, SearchResponseError
from src.services.search_pagination import is_search_results_response
root=Path(__file__).resolve().parent
os.chdir(root)
parser=argparse.ArgumentParser()
parser.add_argument('--account', choices=[p.stem for p in (root/'state').glob('*.json')], default='personal')
args=parser.parse_args()
target=root/'state'/(args.account+'.json')
print('正在验证账号：'+args.account,flush=True)
snapshot=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
status={'ok':False}
async def observe(response):
 if not is_search_results_response(response): return
 status['ok']=False
 try:
  payload=await validate_search_response(response,"登录验证搜索")
  status['ok']=True
  print('搜索接口验证成功，返回商品数：',len(payload['data']['resultList']),flush=True)
 except SearchResponseError as exc:
  print(str(exc)+'；请在本程序打开的验证标签页中处理。',flush=True)
 except Exception as exc:
  print('验证检查异常：'+type(exc).__name__,flush=True)
async def main():
 if browser_for(args.account)=='firefox':
  async with worker_client(args.account) as client:
   response=await client.post('/verify/start');response.raise_for_status()
   print('已打开该账号常驻 Firefox 的验证标签页。',flush=True)
   try:
    while True:
     await asyncio.to_thread(input,'完成验证并搜索看到商品后，回到本窗口按 Enter 保存；取消按 Ctrl+C。\n')
     response=await client.post('/verify/save');response.raise_for_status()
     result=response.json()
     if result['ok']:
      print('已验证搜索并保存到本机。Firefox 将保持打开，验证与采集复用同一配置。',flush=True);break
     print(result['detail'],flush=True)
   finally:
    await client.post('/verify/cancel')
  return
 async with async_playwright() as p:
  shared=True
  if shared:
   browser,context=await attach_shared_chrome(p,snapshot,args.account)
  else:
   browser=await p.chromium.launch(headless=False,channel='chrome')
   context=await browser.new_context(storage_state=storage_from_snapshot(snapshot),**desktop_options())
  page=await context.new_page()
  await page.bring_to_front()
  print('请只在刚打开并置前的验证标签页中登录和搜索。其他 Chrome 页面不受影响。',flush=True)
  page.on('response',observe)
  try: await page.goto('https://www.goofish.com/search?'+urlencode({'q':'aph仏英'}),wait_until='domcontentloaded',timeout=60000)
  except Exception: print('页面加载未完成，请手动查看。')
  while True:
   await asyncio.to_thread(input,'请自行完成验证并搜索。看到商品后回到本窗口按 Enter 检查并保存；取消按 Ctrl+C。\n')
   blocked=any([await page.locator(s).is_visible() for s in ['div.baxia-dialog-mask','div.J_MIDDLEWARE_FRAME_WIDGET']])
   if not status['ok'] or blocked:
    print('尚未确认搜索成功，不覆盖登录态。请完成验证后重新搜索。');continue
   state=await context.storage_state()
   if not any(c.get('name')=='cookie2' and c.get('value') for c in state['cookies']):
    print('未发现登录会话，没有保存。');continue
   backup=root/'data'/'login-backups';backup.mkdir(parents=True,exist_ok=True)
   if target.exists(): shutil.copy2(target,backup/(args.account+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json'))
   pending=target.with_suffix('.pending')
   pending.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');pending.replace(target)
   ids=sorted({c.get('value') for c in state['cookies'] if c.get('name')=='unb' and c.get('value')})
   print('已验证搜索并保存到本机。账号：'+args.account+'；登录用户 ID：'+', '.join(ids),flush=True)
   print('专用 Chrome 将保持打开，请回到聊天告诉我。');break
  if not shared: await browser.close()

asyncio.run(main())
