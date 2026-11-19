"""One authorized live sort check; no collection, failover or login-state writes."""
import asyncio
import os
from src.services.firefox_sort import apply_firefox_publish_sort
from src.services.new_listing_policy import validate_search_response
from src.services.search_pagination import is_search_results_response
from src.services.firefox_sort_evidence import request_summary, payload_summary, page_summary


async def probe_sort_once(runtime, snapshot):
    if os.environ.get('FIREFOX_FULL_SORT_PROBE_ONCE') == '1':
        from src.services.firefox_full_sort_probe import probe_full_sort
        return await probe_full_sort(runtime, snapshot)
    if os.environ.get('FIREFOX_CLICK_DIAGNOSTIC_ONCE') == '1':
        from src.services.firefox_click_probe import diagnose_click_paths
        return await diagnose_click_paths(runtime, snapshot)
    logs = []
    result = {'ok': False, 'stage': 'startup', 'logs': logs}
    page = None
    captured = []
    captures = []
    phase = 'initial'
    async def capture(response):
        entry={'phase':phase,'request':request_summary(response.request)}
        try:
            payload=await response.json()
            entry.update(payload_summary(payload))
        except Exception:
            entry['payload_unavailable']=True
        captured.append(entry)
    def observe(response):
        if is_search_results_response(response):
            captures.append(asyncio.create_task(capture(response)))
    try:
        context = await runtime.get_context(snapshot)
        page = await context.new_page()
        page.on('response',observe)
        result['stage'] = 'initial_search'
        async with page.expect_response(is_search_results_response, timeout=30000) as pending:
            await page.goto('https://www.goofish.com/search?q=aph%E4%BB%8F%E8%8B%B1',
                            wait_until='domcontentloaded', timeout=60000)
        await validate_search_response(await pending.value, '验证初始搜索')
        # Give the initial response a chance to render; actual checks still wait
        # on the DOM, not just a fixed delay.
        container = page.locator("div[class*='search-select-container']").filter(
            has=page.locator("div[class*='search-select-items-container']").get_by_text('最新', exact=True))
        title = container.locator("div[class*='search-select-title-container']")
        await title.wait_for(state='visible', timeout=10000)
        before = (await title.inner_text()).strip()
        result['title_before'] = before if before in ('新发布', '最新', '1天内', '3天内', '7天内', '14天内') else 'other'
        result['stage'] = 'sort'
        phase = 'sort'
        async def wait_after_click(low, high):
            await asyncio.sleep(low)
        response = await apply_firefox_publish_sort(page, '最新', logger=logs.append, wait_after_click=wait_after_click)
        payload = await validate_search_response(response, '验证排序结果')
        result['selected_request']=request_summary(response.request)
        result['selected_response']=payload_summary(payload)
        result['rendered_cards']=await page_summary(page)
        refs=[row['item_ref'] for row in result['selected_response']['rows']]
        rendered=[row['item_ref'] for row in result['rendered_cards']]
        result['dom_equals_response_order']=rendered==refs
        items = payload['data']['resultList']
        timestamps = []
        for item in items:
            try:
                value = item['data']['item']['main']['clickParam']['args']['publishTime']
                if str(value).isdigit():
                    timestamps.append(int(value))
            except (KeyError, TypeError):
                pass
        result.update(ok=True, stage='complete', title_after='最新', http_status=response.status,
                      response_method=response.request.method, items=len(items),
                      publication_timestamps=len(timestamps),
                      publications_descending=all(a >= b for a,b in zip(timestamps,timestamps[1:])) if len(timestamps)>1 else None)
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        # Details are only the sorter module's sanitized stage/counter messages.
    finally:
        if page is not None:
            page.remove_listener('response',observe)
            if captures:
                try:
                    await asyncio.wait_for(asyncio.gather(*captures),timeout=10)
                except Exception:
                    result['capture_incomplete']=True
            result['search_responses']=captured
            try:
                await page.close()
                result['test_page_closed'] = True
            except Exception:
                result['test_page_closed'] = False
    return result
