"""Attach only to an already-open eligible account; never launch, rebind or thaw."""
import json
import sqlite3
from pathlib import Path
import httpx
from src.services.account_nodes import account_nodes
from src.services.history_detail import inspect_detail

ROOT=Path(__file__).resolve().parents[2]

def select_account(task):
    with sqlite3.connect((ROOT/'data/account-failover.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT account FROM active WHERE task=?',(task.task_name,)).fetchone()
    preferred=Path(row[0]).stem if row else Path(task.account_state_file or '').stem
    eligible=[n for n in account_nodes(root=ROOT)['nodes'] if n['status'] in ('active','available')]
    eligible.sort(key=lambda n:n['name']!=preferred)
    from src.services.shared_chrome import _endpoint,profile_for
    for node in eligible:
        name=node['name']
        if node['browser']=='firefox':
            try:
                info=json.loads((ROOT/'data'/('firefox-'+name)/'worker.json').read_text())
                with httpx.Client(base_url='http://127.0.0.1:'+str(int(info['port'])),
                    headers={'Authorization':'Bearer '+info['token']},trust_env=False,timeout=2) as client:
                    response=client.get('/health');response.raise_for_status();health=response.json()
                if health.get('account')==name and health.get('browser_open') and health.get('history_detail_version')==1:
                    return name,'firefox'
            except (OSError,ValueError,KeyError,httpx.HTTPError):pass
        if node['browser'] in ('chrome','edge') and _endpoint(profile_for(name)):return name,node['browser']
    raise RuntimeError('没有可用且已连接的常驻浏览器；未启动、解冻或切换任何账号')

def ensure_account_available(account):
    node=next((n for n in account_nodes(root=ROOT)['nodes'] if n['name']==account),None)
    if not node or node['status'] not in ('active','available'):
        raise RuntimeError('本次账号已进入冷却或不可用，核验停止；未切换账号')

class HistoryBrowser:
    def __init__(self,account,browser):
        self.account=account;self.browser=browser;self.client=None;self.playwright=None;self.page=None
    async def open(self):
        ensure_account_available(self.account)
        if self.browser=='firefox':
            info=json.loads((ROOT/'data'/('firefox-'+self.account)/'worker.json').read_text(encoding='utf-8'))
            self.client=httpx.AsyncClient(base_url='http://127.0.0.1:'+str(int(info['port'])),
                headers={'Authorization':'Bearer '+info['token']},trust_env=False,timeout=40)
            response=await self.client.get('/health');response.raise_for_status();health=response.json()
            if health.get('account')!=self.account or not health.get('browser_open'):
                raise RuntimeError('该账号常驻Firefox未打开；未自动启动浏览器')
            if health.get('history_detail_version')!=1:raise RuntimeError('Firefox后台尚未加载历史核验功能')
        else:
            from playwright.async_api import async_playwright
            from src.services.shared_chrome import _endpoint,profile_for
            endpoint=_endpoint(profile_for(self.account))
            if not endpoint:raise RuntimeError('该账号常驻浏览器已断开，未自动启动')
            self.playwright=await async_playwright().start()
            browser=await self.playwright.chromium.connect_over_cdp(endpoint);self.context=browser.contexts[0]
            snapshot=json.loads((ROOT/'state'/(self.account+'.json')).read_text(encoding='utf-8'))
            expected={c['value'] for c in snapshot.get('cookies',[]) if c['name']=='unb'}
            actual={c['value'] for c in await self.context.cookies('https://www.goofish.com') if c['name']=='unb'}
            if not expected or expected!=actual:raise RuntimeError('浏览器账号身份不一致，请先完成该账号验证')
            self.page=await self.context.new_page()
    async def check(self,run_id,item_id):
        ensure_account_available(self.account)
        if self.browser=='firefox':
            response=await self.client.post('/history/detail',json={'run_id':run_id,'item_id':item_id})
            if response.status_code==409:raise RuntimeError('Firefox忙碌或需要先完成账号验证，本次核验停止')
            response.raise_for_status();return response.json()
        if self.page is None or self.page.is_closed():self.page=await self.context.new_page()
        try:return await inspect_detail(self.page,item_id)
        finally:
            if not self.page.is_closed():
                try:await self.page.goto('about:blank',timeout=3000)
                except Exception:await self.page.close()
    async def close(self,run_id):
        try:
            if self.client is not None:
                try:await self.client.post('/history/cancel',json={'run_id':run_id},timeout=8)
                finally:await self.client.aclose()
            if self.page is not None and not self.page.is_closed():await self.page.close()
        finally:
            # Disconnect our client, never close the owner's shared browser.
            if self.playwright is not None:await self.playwright.stop()
