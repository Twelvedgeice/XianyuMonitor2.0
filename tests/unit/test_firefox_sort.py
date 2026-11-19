"""Offline Firefox fixture based on user-supplied DOM screenshots, not live-site proof."""
import asyncio
import json
import os

import pytest
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from src.services.firefox_sort import apply_firefox_publish_sort
from src.services.new_listing_policy import SearchResponseError, SearchVerificationError


MENU = '''<div class="search-select-container--fixture">
  <div class="search-select-title-container--fixture" onclick="this.nextElementSibling.style.display='block'">
    <span class="search-select-title--fixture">TITLE</span><div class="search-select-arrow--fixture"></div>
  </div>
  <div class="search-select-items-container-fixture" style="display:none">
    <div class="search-select-item--fixture" onclick="choose(this)">最新</div>
    <div class="search-select-item--fixture" onclick="choose(this)">1天内</div>
    <div class="search-select-item--fixture" onclick="choose(this)">3天内</div>
    <div class="search-select-item--fixture" onclick="choose(this)">7天内</div>
    <div class="search-select-item--fixture" onclick="choose(this)">14天内</div>
  </div>
</div>'''


def test_sort_in_isolated_firefox():
    async def run():
        async with async_playwright() as pw:
            browser = await pw.firefox.launch(headless=True, env={**os.environ, 'MOZ_DISABLE_SAFE_MODE_KEY': '1'})
            cases = [
                ('new_title', '新发布', '最新', '', None),
                ('selected_title', '最新', '最新', '', None),
                ('days_option', '最新', '3天内', '', None),
                ('blocked_title', '新发布', '最新', 'overlay', 'open_menu'),
                ('no_response', '新发布', '最新', 'no_response', 'wait_response'),
                ('wrong_method', '新发布', '最新', 'get', 'wait_response'),
                ('wrong_title', '新发布', '最新', 'wrong_title', 'confirm_title'),
                ('verification', '新发布', '最新', 'verify', 'verification'),
                ('duplicate_menu', '新发布', '最新', 'duplicate', 'locate_menu'),
            ]
            try:
                for name, title, option, mode, expected in cases:
                    context = await browser.new_context()
                    page = await context.new_page()
                    logs, requests = [], []
                    markup = MENU.replace('TITLE', title)
                    if mode == 'duplicate':
                        markup += MENU.replace('TITLE', title)
                    # A distracting page-wide 最新 text must never become the option.
                    html = '<meta charset="utf-8"><div>最新</div>' + markup + '''<script>
                    async function choose(el) {
                        if (MODE !== 'wrong_title') el.parentElement.previousElementSibling.querySelector('span').textContent=el.textContent;
                        el.parentElement.style.display='none';
                        if (MODE !== 'no_response') await fetch('/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/', {method: MODE === 'get' ? 'GET' : 'POST'});
                    }</script>'''.replace('MODE', json.dumps(mode))
                    if mode == 'overlay':
                        html += '<div style="position:fixed;inset:0;z-index:999;background:white">overlay</div>'

                    async def route_request(route):
                        if route.request.resource_type == 'document':
                            await route.fulfill(status=200, content_type='text/html', body=html)
                        else:
                            requests.append(route.request.method)
                            payload = {'ret': ['FAIL_SYS_USER_VALIDATE::SECRET'] if mode == 'verify' else ['SUCCESS::ok'],
                                       'data': {'resultList': []}}
                            await route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
                    await context.route('**/*', route_request)
                    await page.goto('http://sort-fixture.test/')
                    async def no_sleep(a, b):
                        pass
                    try:
                        if name == 'selected_title':
                            # Reproduce the old first-click failure on the observed selected-title state.
                            with pytest.raises(PlaywrightTimeoutError):
                                await page.click('text=新发布', timeout=150)
                        if expected:
                            error_type = SearchVerificationError if expected == 'verification' else SearchResponseError
                            with pytest.raises(error_type) as caught:
                                await apply_firefox_publish_sort(page, option, logger=logs.append,
                                    wait_after_click=no_sleep, click_timeout=350, response_timeout=900)
                            if expected != 'verification':
                                assert 'stage=' + expected in str(caught.value), (name, str(caught.value))
                            assert 'SECRET' not in str(caught.value) + '\n'.join(logs)
                        else:
                            response = await apply_firefox_publish_sort(page, option, logger=logs.append,
                                wait_after_click=no_sleep, click_timeout=1500, response_timeout=1500)
                            assert response.ok
                            assert requests == ['POST']
                            assert await page.locator('[class*=search-select-title--]').inner_text() == option
                        if name == 'blocked_title':
                            assert requests == []
                            assert any('pointer_intercepted' in line for line in logs)
                        print('PASS', name)
                    finally:
                        await context.close()
            finally:
                await browser.close()
    asyncio.run(run())
