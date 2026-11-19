import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.task_outcome import TaskSkipped


def test_empty_pool_skips_before_browser_or_notification(monkeypatch):
    import src.scraper as scraper
    monkeypatch.setattr(scraper, "load_cutoff", lambda _: None)
    monkeypatch.setattr(scraper, "load_price_snapshots", lambda _: [])
    monkeypatch.setattr(scraper, "load_processed_link_keys", lambda _: set())
    monkeypatch.setattr(scraper, "load_state_files", lambda _: [])
    monkeypatch.setattr(scraper, "failover_enabled", lambda: True)
    monkeypatch.setattr(scraper, "resolve_account_runtime_plan", lambda **_: {
        "forced_account": None, "prefer_root_state": False, "use_account_pool": True})
    pool = SimpleNamespace(select=Mock(return_value=None))
    monkeypatch.setattr(scraper, "AccountFailover", lambda **_: pool)
    browser = Mock(side_effect=AssertionError("must not open browser"))
    notify = AsyncMock(side_effect=AssertionError("must not notify"))
    monkeypatch.setattr(scraper, "playwright_scope", browser)
    monkeypatch.setattr(scraper, "send_ntfy_notification", notify)
    with pytest.raises(TaskSkipped, match="本轮未检查闲鱼"):
        asyncio.run(scraper.scrape_xianyu({"task_name": "test", "keyword": "test", "decision_mode": "keyword"}))
    pool.select.assert_called_once()
    browser.assert_not_called()
    notify.assert_not_called()


@pytest.mark.parametrize("outcome, expected, forbidden", [
    (TaskSkipped("no eligible account"), "[任务跳过]", "正常结束"),
    (0, "正常结束，本次运行共处理了 0 个新商品", "[任务跳过]"),
    (RuntimeError("test error"), "因异常而终止", "正常结束"),
])
def test_cli_distinguishes_skipped_success_and_failure(monkeypatch, capsys, outcome, expected, forbidden):
    import spider_v2
    task = {"task_name": "test", "enabled": True, "keyword": "test", "decision_mode": "keyword", "account_state_file": "fake.json"}
    repository = SimpleNamespace(find_all=AsyncMock(return_value=[SimpleNamespace(dict=lambda: task)]))
    monkeypatch.setattr(spider_v2, "SqliteTaskRepository", lambda: repository)
    monkeypatch.setattr(spider_v2.sys, "argv", ["spider_v2.py"])
    async def fake_scrape(**kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(spider_v2, "scrape_xianyu", fake_scrape)
    asyncio.run(spider_v2.main())
    output = capsys.readouterr().out
    assert expected in output
    assert forbidden not in output
