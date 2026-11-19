"""Read-only detail verification. Only explicit current-item evidence means sold."""
import asyncio
import re
import json
from urllib.parse import urlsplit,parse_qs
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

DETAIL_API='/h5/mtop.taobao.idle.pc.detail/'
SOLD_MARKER='O1CN01XvUrci1XK59jkqafe_'
OFFLINE_MARKER='O1CN016Us3b321aVpzyxCA4_'
SOLD_TEXT={'卖掉了','已卖出','已售出','该宝贝已卖出','该商品已卖出','宝贝已卖出'}
STATUS_SELECTORS="[class*='item-status--'],[class*='sellerButton--'],[data-testid='item-status']"

def result(status,reason='',*,source='detail_page',evidence='',asking_price=None,stop=False):
    return dict(status=status,reason=reason,source=source,evidence=evidence,
                asking_price=asking_price,stop=stop)

def canonical_url(item_id):
    value=str(item_id)
    if not re.fullmatch(r'[0-9]{1,30}',value):raise ValueError('历史商品ID无效')
    return 'https://www.goofish.com/item?id='+value

def same_item(url,item_id):
    parts=urlsplit(url)
    return parts.scheme=='https' and parts.hostname in ('www.goofish.com','goofish.com') and parts.path=='/item' and parse_qs(parts.query).get('id')==[str(item_id)]

def classify_payload(payload,item_id):
    if not isinstance(payload,dict):return None
    ret=payload.get('ret')
    if not isinstance(ret,list):return None
    codes=[str(code).split('::',1)[0] for code in ret]
    if any('USER_VALIDATE' in code or 'RGV' in code for code in codes):
        return result('failed','需要人工验证，已停止',source='detail_api',stop=True)
    if any('SESSION_EXPIRED' in code or 'LOGIN' in code for code in codes):
        return result('failed','登录失效，已停止',source='detail_api',stop=True)
    if 'FAIL_BIZ_ITEM_DEL_NOT_FOUND' in codes:
        return result('unavailable','详情接口明确返回商品不存在；不等于已卖出',source='detail_api')
    if not any(code=='SUCCESS' for code in codes):return None
    data=payload.get('data') or {}
    if not isinstance(data,dict):return None
    item=data.get('itemDO') or {}
    if not isinstance(item,dict):return None
    actual=item.get('itemId') or (data.get('trackParams') or {}).get('itemId')
    if str(actual)!=str(item_id):return None
    state=item.get('itemStatusStr');price=item.get('soldPrice')
    if not isinstance(state,str):return None
    # Official xy-site/0.0.183 p_item-index.js: BOUGHT=卖掉了, OFFLINE=已下架, ONLINE=在线.
    # soldPrice is the field rendered as the item's displayed price, NOT a proven transaction price.
    if state in SOLD_TEXT:return result('sold',source='detail_api',evidence='itemDO.itemStatusStr='+state,asking_price=price)
    if state=='已下架':return result('unavailable','当前商品已下架；不等于已卖出',source='detail_api',evidence='itemDO.itemStatusStr=已下架',asking_price=price)
    if state=='在线':return result('available',source='detail_api',evidence='itemDO.itemStatusStr=在线',asking_price=price)
    return None

def request_item_id(request):
    try:
        fields=parse_qs(urlsplit(request.url).query)
        body=request.post_data or ''
        if body:
            try: fields.update(json.loads(body))
            except ValueError:fields.update(parse_qs(body))
        data=fields.get('data',{})
        if isinstance(data,list):data=data[0]
        if isinstance(data,str):data=json.loads(data)
        return str(data.get('itemId')) if isinstance(data,dict) and data.get('itemId') is not None else None
    except (ValueError,TypeError,AttributeError):return None

async def inspect_detail(page,item_id,*,settle_seconds=10):
    """Navigate only a canonical historical item URL, observe; never click trade actions."""
    try:url=canonical_url(item_id)
    except ValueError:return result('failed','历史商品ID无效，未访问外部网址')
    signals=[];tasks=[];requested=False;responded=False;transport_failed=False
    def relevant(req):return DETAIL_API in req.url and request_item_id(req) in (None,str(item_id))
    def request(req):
        nonlocal requested
        if relevant(req):requested=True
    def failed(req):
        nonlocal transport_failed
        if relevant(req):transport_failed=True
    async def response(res):
        nonlocal responded
        if not relevant(res.request):return
        responded=True
        if res.status in (401,403,429):
            signals.append(result('failed','详情接口拒绝访问或限流，已停止',source='detail_api',stop=True));return
        try:
            payload=await res.json()
            value=classify_payload(payload,item_id)
            if value and value['status']=='unavailable' and request_item_id(res.request)!=str(item_id):value=None
            if value:signals.append(value)
        except Exception:pass
    def observe(res):tasks.append(asyncio.create_task(response(res)))
    page.on('request',request);page.on('requestfailed',failed);page.on('response',observe)
    try:
        doc=await page.goto(url,wait_until='domcontentloaded',timeout=20000)
        if 'passport.goofish.com' in page.url or '/login' in urlsplit(page.url).path:
            return result('failed','详情跳转登录页，已停止',stop=True)
        if not same_item(page.url,item_id):return result('unknown','页面跳转，未获得原商品状态')
        if doc and doc.status in (401,403,429):return result('failed','详情页拒绝访问或限流，已停止',stop=True)
        if doc and doc.status in (404,410):return result('unavailable','详情页不存在；不等于已卖出')
        if doc and doc.status>=400:return result('failed','详情页HTTP异常，已停止',stop=True)
        deadline=asyncio.get_running_loop().time()+settle_seconds
        while True:
            if not same_item(page.url,item_id):return result('failed','详情发生跳转，核验停止',stop=True)
            # Guard against a visible challenge before trusting status text.
            for selector in ('div.baxia-dialog-mask','div.J_MIDDLEWARE_FRAME_WIDGET'):
                if await page.locator(selector).first.is_visible():
                    return result('failed','页面需要人工验证，已停止',stop=True)
            for text in ('请先登录','滑动验证','请完成验证'):
                if await page.get_by_text(text,exact=True).first.is_visible():
                    return result('failed','页面需要登录或人工验证，已停止',stop=True)
            critical=next((s for s in signals if s.get('stop')),None)
            if critical:return critical
            if signals:return signals[-1]
            badges=page.locator(STATUS_SELECTORS)
            for index in range(min(await badges.count(),15)):
                badge=badges.nth(index)
                if not await badge.is_visible():continue
                text=(await badge.inner_text()).strip()
                if text in SOLD_TEXT:return result('sold',evidence='详情状态控件：'+text)
                if text=='已下架':return result('unavailable','详情状态控件显示已下架',evidence='详情状态控件：已下架')
                for image in await badge.locator('img').all():
                    src=await image.get_attribute('src') or ''
                    if urlsplit(src).hostname not in ('img.alicdn.com','gw.alicdn.com'):continue
                    if SOLD_MARKER in src:return result('sold',evidence='详情官方“卖掉了”状态水印')
                    if OFFLINE_MARKER in src:return result('unavailable','详情官方下架水印；不等于已卖出')
            if transport_failed:return result('failed','详情接口连接失败，已停止',stop=True)
            if asyncio.get_running_loop().time()>=deadline:
                return result('failed','详情接口未完成，已停止',stop=True) if requested and not responded else result('unknown','未发现当前商品的明确状态证据')
            await asyncio.sleep(.2)
    except PlaywrightTimeoutError:return result('failed','详情加载超时，已停止',stop=True)
    except Exception:return result('failed','详情读取失败，已停止',stop=True)
    finally:
        page.remove_listener('request',request);page.remove_listener('requestfailed',failed);page.remove_listener('response',observe)
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)


class FirefoxHistoryPages:
    """Worker-owned pages, separate from monitoring; idle pages are always about:blank."""
    def __init__(self,runtime):self.runtime=runtime;self.pages={};self.active=None
    async def check(self,run_id,item_id):
        if not self.runtime.context:raise RuntimeError('常驻Firefox未打开，请先连接该账号')
        page=self.pages.get(run_id)
        if page is None or page.is_closed():
            page=await self.runtime.context.new_page();self.pages[run_id]=page
        self.active=run_id
        try:return await inspect_detail(page,item_id)
        finally:
            self.active=None
            if not page.is_closed():
                try:await page.goto('about:blank',timeout=3000)
                except Exception:
                    await page.close();self.pages.pop(run_id,None)
    async def close(self,run_id):
        page=self.pages.pop(run_id,None)
        if page is not None and not page.is_closed():await page.close()
