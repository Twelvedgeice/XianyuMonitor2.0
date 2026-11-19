"""Firefox publish-sort controls, scoped to the observed menu DOM."""
import asyncio
import json

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.services.new_listing_policy import SearchResponseError, validate_search_response
from src.services.search_pagination import is_search_results_response


async def apply_firefox_publish_sort(page, option, *, logger, wait_after_click,
                                     click_timeout=10000, response_timeout=20000):
    # The title changes from 新发布 to the selected option. Identify the menu by
    # its own 最新 item, not the current title or an arbitrary page-wide match.
    menu_selector = "div[class*='search-select-items-container']"
    menus = page.locator(menu_selector)
    container = page.locator("div[class*='search-select-container']").filter(
        has=menus.get_by_text('最新', exact=True))
    title = container.locator("div[class*='search-select-title-container']")
    menu = container.locator(menu_selector)
    item = menu.get_by_text(option, exact=True)
    stage = 'locate_menu'
    try:
        logger('[Firefox排序] stage=locate_menu')
        await container.wait_for(state='visible', timeout=click_timeout)
        stage = 'open_menu'
        logger('[Firefox排序] stage=open_menu')
        # Official CSS opens this menu via :hover, not a title click toggle.
        # Keep the pointer in the menu; a random pause here loses hover state.
        await title.hover(timeout=click_timeout)
        await item.wait_for(state='visible', timeout=click_timeout)
        await item.hover(timeout=click_timeout)
        stage = 'select_option'
        logger('[Firefox排序] stage=select_option')
        async with page.expect_response(is_search_results_response, timeout=response_timeout) as pending:
            await item.click(timeout=click_timeout)
            stage = 'wait_response'
            logger('[Firefox排序] stage=wait_response')
        response = await pending.value
        stage = 'validate_response'
        await validate_search_response(response, '最新发布排序')
        # A successful unrelated search must not hide an unchanged menu title.
        stage = 'confirm_title'
        await title.get_by_text(option, exact=True).wait_for(state='visible', timeout=click_timeout)
        await wait_after_click(2, 4)
        logger('[筛选响应] 最新发布排序成功（Firefox）')
        return response
    except SearchResponseError:
        logger('[Firefox排序] stage=validate_response failed')
        raise
    except Exception as exc:
        # Never print raw Playwright errors: they may embed URLs or page data.
        message = str(exc).lower()
        hints = [name for name, marker in (
            ('pointer_intercepted', 'intercepts pointer events'),
            ('not_visible', 'not visible'),
            ('detached', 'detached'),
            ('multiple_matches', 'strict mode violation'),
            ('closed', 'has been closed'),
        ) if marker in message]
        evidence = {'stage': stage, 'error': 'timeout' if isinstance(exc, PlaywrightTimeoutError) else 'operation_failed',
                    'hints': hints}

        async def counts():
            return {'menus': await container.count(), 'titles': await title.count(),
                    'options': await item.count(), 'visible_options': await item.locator('visible=true').count()}

        try:
            evidence.update(await asyncio.wait_for(counts(), timeout=2))
        except Exception:
            evidence['snapshot'] = 'unavailable'
        logger('[Firefox排序诊断] ' + json.dumps(evidence, ensure_ascii=False))
        # Fail closed even if no publication cutoff was configured. This error
        # type bypasses the old catch-all that used to discard the failed stage.
        raise SearchResponseError('最新发布排序失败：stage=' + stage +
                                  '；未确认排序响应，停止本轮。') from None
