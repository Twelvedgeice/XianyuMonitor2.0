import os
from pathlib import Path
from dotenv import dotenv_values
import httpx
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parent
config=dotenv_values(root/'.env')
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(root/'.browsers')
base='http://127.0.0.1:8765'
with httpx.Client(base_url=base, trust_env=False) as client:
    assert client.get('/health').status_code==200
    assert client.get('/api/accounts').status_code==401
    assert client.post('/auth/status',json={'username':'admin','password':'incorrect'}).status_code==401
    assert client.post('/auth/status',json={'username':config['WEB_USERNAME'],'password':config['WEB_PASSWORD']}).status_code==200
    assert client.get('/api/accounts').json()==[]
    assert client.get('/api/tasks').status_code==200
    assert client.post('/auth/logout').status_code==200
    assert client.get('/api/accounts').status_code==401
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel='chromium')
    page=browser.new_page(viewport={'width':1365,'height':900})
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    page.goto(base)
    page.locator('#username').fill(config['WEB_USERNAME'])
    page.locator('#password').fill(config['WEB_PASSWORD'])
    page.locator('button[type=submit]').click()
    page.wait_for_url('**/dashboard')
    page.get_by_role('link',name='任务管理').wait_for()
    page.screenshot(path=str(root/'dashboard-preview.png'),full_page=True)
    page.goto(base+'/accounts')
    page.wait_for_load_state('networkidle')
    assert page.request.get(base+'/api/accounts').status==200
    assert not errors, errors
    browser.close()
(root/'local-access.txt').write_text('管理地址：http://127.0.0.1:8765\n用户名：'+config['WEB_USERNAME']+'\n密码：'+config['WEB_PASSWORD']+'\n这是本机管理面板密码，不是闲鱼密码。请勿分享此文件。\n',encoding='utf-8')
print('PASS: health, unauthorized API rejection, incorrect password rejection, session login/logout, browser login, dashboard/accounts rendering; no JS errors.')
