"""Bounded private3 comparison of direct navigation and scraper page preparation."""
import asyncio
from pathlib import Path
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from src.services.search_pagination import is_search_results_response
from src.services.new_listing_policy import validate_search_response

SEARCH='https://www.goofish.com/search?q=aph%E4%BB%8F%E8%8B%B1'
MARKERS=('waiting for locator','locator resolved','attempting click action',
         'waiting for element to be visible, enabled and stable','element is visible, enabled and stable',
         'element is not stable','element is not visible','element is not enabled',
         'scrolling into view if needed','done scrolling','outside of the viewport',
         'intercepts pointer events','performing click action','click action done',
         'waiting for scheduled navigations','navigations have finished','strict mode violation')

def safe_error(exc):
    message=str(exc).lower()
    return {'type':type(exc).__name__,'action_log':{m:message.count(m) for m in MARKERS if m in message}}

async def inspect(page,title):
    state=await page.evaluate('''async () => {
        let frames=0, running=true;
        const tick=()=>{frames++; if(running) requestAnimationFrame(tick)};
        requestAnimationFrame(tick);
        await new Promise(r=>setTimeout(r,400)); running=false;
        let geo='unknown'; try {geo=(await navigator.permissions.query({name:'geolocation'})).state}catch(e){}
        return {visibility:document.visibilityState,focused:document.hasFocus(),
          inner:[innerWidth,innerHeight],outer:[outerWidth,outerHeight],scroll:[scrollX,scrollY],
          frames_in_400ms:frames,active_animations:document.getAnimations().filter(a=>a.playState==='running').length,
          geolocation_permission:geo};
    }''')
    state['title']=await title.evaluate('''el=>{
        const r=el.getBoundingClientRect(),c=getComputedStyle(el);
        const x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);
        return {rect:[r.x,r.y,r.width,r.height],display:c.display,visibility:c.visibility,
          pointerEvents:c.pointerEvents,center_hit_target:!!hit && (hit===el || el.contains(hit)),
          hit_tag:hit?.tagName};
    }''')
    return state

async def diagnose_click_paths(runtime,snapshot):
    result={'ok':False,'cases':[]}
    page=None
    try:
        context=await runtime.get_context(snapshot)
        page=await context.new_page()
        for name in ('fresh_direct','reused_home_scroll_search'):
            case={'name':name};result['cases'].append(case)
            if name=='reused_home_scroll_search':
                await page.goto('https://www.goofish.com/',wait_until='domcontentloaded',timeout=30000)
                await asyncio.sleep(1)
                await page.evaluate('window.scrollBy(0,450)')
                await asyncio.sleep(1)
            async with page.expect_response(is_search_results_response,timeout=30000) as pending:
                await page.goto(SEARCH,wait_until='domcontentloaded',timeout=60000)
            await validate_search_response(await pending.value,'诊断初始搜索')
            await page.wait_for_selector('text=新发布',timeout=15000)
            if name=='reused_home_scroll_search':
                await asyncio.sleep(2)
                for selector in ('div.baxia-dialog-mask','div.J_MIDDLEWARE_FRAME_WIDGET'):
                    try:
                        await page.locator(selector).wait_for(state='visible',timeout=2000)
                        case['verification_overlay']=True
                        return result
                    except PlaywrightTimeoutError:
                        pass
                try:
                    await page.click("div[class*='closeIconBg']",timeout=3000)
                    case['ad_close']='clicked'
                except PlaywrightTimeoutError as exc:
                    case['ad_close']=safe_error(exc)
            container=page.locator("div[class*='search-select-container']").filter(
                has=page.locator("div[class*='search-select-items-container']").get_by_text('最新',exact=True))
            title=container.locator("div[class*='search-select-title-container']")
            option=container.locator("div[class*='search-select-items-container']").get_by_text('最新',exact=True)
            case['before']=await inspect(page,title)
            for trial in (True,False):
                key='trial' if trial else 'actual_click'
                try:
                    await title.click(trial=trial,timeout=5000)
                    case[key]={'ok':True}
                except Exception as exc:
                    case[key]={'ok':False,**safe_error(exc)}
            case['menu_visible']=await option.is_visible()
            case['after']=await inspect(page,title)
            if not case['actual_click']['ok']:
                file=Path('data/browser-diagnostics/private_3')/('click-path-'+name+'.png')
                await page.screenshot(path=str(file))
                case['screenshot']=file.name
                await page.bring_to_front()
                case['after_front']=await inspect(page,title)
                try:
                    await title.click(timeout=5000)
                    case['front_click']={'ok':True,'menu_visible':await option.is_visible()}
                except Exception as exc:
                    case['front_click']={'ok':False,**safe_error(exc)}
        result['ok']=True
    except Exception as exc:
        result['error']=safe_error(exc)
    finally:
        if page is not None:
            await page.close()
            result['test_page_closed']=True
    return result
