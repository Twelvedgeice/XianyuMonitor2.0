"""Persistent account selection, configurable cooldowns and switch notifications."""
import asyncio
import hashlib
import os
from pathlib import Path
import sqlite3
import uuid
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from src.infrastructure.config.env_manager import env_manager


def load_rotation_policy():
    """Read once per round, including in long-lived Firefox workers.

    The settings page and scraper share these global keys. Task-level legacy
    overrides must not silently replace the policy shown on the settings page.
    """
    values = env_manager.read_env()

    def integer(key, default, minimum):
        try:
            value = int(values.get(key, os.getenv(key, str(default))))
            return value if value >= minimum else default
        except (TypeError, ValueError):
            return default

    return {
        "account_retry_limit": integer("ACCOUNT_ROTATION_RETRY_LIMIT", 2, 1),
        "account_blacklist_ttl": integer("ACCOUNT_BLACKLIST_TTL", 21600, 0),
        "account_state_dir": values.get("ACCOUNT_STATE_DIR", os.getenv("ACCOUNT_STATE_DIR", "state")) or "state",
    }


def enabled():
    return os.getenv("LOCAL_ACCOUNT_FAILOVER", "").lower() == "true"


def replaces_task_pause(reason):
    # Managed account failover owns all collection failures. A legacy task-wide
    # pause must not stop healthy standby accounts from being selected.
    return enabled()


class AccountFailover:
    def __init__(self, path="data/account-failover.sqlite3", *, clock=None, cooldown_seconds=6 * 60 * 60):
        self.path = str(path)
        self.clock = clock or time.time
        self.cooldown_seconds = cooldown_seconds
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("CREATE TABLE IF NOT EXISTS blocked (account TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)")
            if 'cooldown_until' not in {row[1] for row in db.execute('PRAGMA table_info(blocked)')}:
                db.execute('ALTER TABLE blocked ADD COLUMN cooldown_until REAL')
                for account, fingerprint in db.execute('SELECT account, fingerprint FROM blocked').fetchall():
                    if self.fingerprint(account) == fingerprint:
                        db.execute('UPDATE blocked SET cooldown_until=? WHERE account=?', (self.clock() + self.cooldown_seconds, account))
                    else:
                        db.execute('DELETE FROM blocked WHERE account=?', (account,))
            db.execute("CREATE TABLE IF NOT EXISTS active (task TEXT PRIMARY KEY, account TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS pending_success (task TEXT PRIMARY KEY, account TEXT NOT NULL, switch_id TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def key(path):
        return str(Path(path).resolve())

    @staticmethod
    def fingerprint(path):
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:
            return None

    def _select(self, db, task, files, preferred=None):
        # Eligibility is checked from local files/timestamps only. Standby and
        # cooling accounts must never issue periodic browser/search requests.
        available = []
        for path in files:
            key = self.key(path)
            fingerprint = self.fingerprint(path)
            if fingerprint is None:
                continue
            blocked = db.execute("SELECT cooldown_until FROM blocked WHERE account=?", (key,)).fetchone()
            if blocked and blocked[0] is not None and blocked[0] > self.clock():
                continue
            available.append(key)
        row = db.execute("SELECT account FROM active WHERE task=?", (task,)).fetchone()
        priority = [row[0] if row else None, self.key(preferred) if preferred else None]
        selected = next((p for p in priority if p in available), available[0] if available else None)
        if selected:
            db.execute("INSERT OR REPLACE INTO active VALUES (?,?)", (task, selected))
            if row and row[0] != selected:
                db.execute('INSERT OR REPLACE INTO pending_success VALUES (?,?,?)', (task, selected, uuid.uuid4().hex))
        return selected

    def select(self, task, files, preferred=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._select(db, task, files, preferred)

    def block_and_select(self, task, account, files):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._freeze(db, account)
            selected = self._select(db, task, files)
            db.execute('DELETE FROM pending_success WHERE task=?', (task,))
            if selected:
                db.execute('INSERT INTO pending_success VALUES (?,?,?)', (task, selected, uuid.uuid4().hex))
            return selected

    def _freeze(self, db, account):
        until = self.clock() + self.cooldown_seconds
        db.execute('INSERT OR REPLACE INTO blocked (account,fingerprint,cooldown_until) VALUES (?,?,?)',
                   (self.key(account), self.fingerprint(account) or 'missing', until))
        return until

    def freeze(self, account):
        with self.connect() as db:
            return self._freeze(db, account)

    def cooldown_until(self, account):
        with self.connect() as db:
            row = db.execute('SELECT cooldown_until FROM blocked WHERE account=?', (self.key(account),)).fetchone()
            return row[0] if row else None

    def pending_confirmation(self, task, account):
        with self.connect() as db:
            row = db.execute('SELECT switch_id FROM pending_success WHERE task=? AND account=?',
                             (task, self.key(account))).fetchone()
            return row[0] if row else None

    def acknowledge_confirmation(self, task, switch_id):
        with self.connect() as db:
            db.execute('DELETE FROM pending_success WHERE task=? AND switch_id=?', (task, switch_id))


async def retry_verification(operation, verification_errors, *, attempts=2, retry_delay=5,
                             sleep=asyncio.sleep, logger=print, label="验证重试"):
    """Configured total attempts on the SAME account; cancellation propagates."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for number in range(1, attempts + 1):
        try:
            return await operation()
        except verification_errors:
            logger(f"[{label}] 当前账号第 {number}/{attempts} 次尝试失败")
            if number == attempts:
                raise
            await sleep(retry_delay)


async def retry_collection(operation, *, attempts=2, retry_delay=5, sleep=asyncio.sleep, logger=print,
                           diagnostic_account=None, diagnostic_task=None):
    """One shared budget for timeout, verification, search and filter errors.

    Cancellation/SystemExit are BaseException, and never rotate an account.
    """
    failures = []

    async def tracked_operation():
        try:
            return await operation()
        except Exception as error:
            failures.append(error)
            if len(failures) == 2 and diagnostic_account is not None:
                try:
                    from src.services.browser_diagnostics import diagnose_failure
                    report = await diagnose_failure(diagnostic_account, tuple(failures), task=diagnostic_task)
                    logger(f"[浏览器诊断] 连续两次失败，排查报告：{report}")
                except Exception:
                    logger("[浏览器诊断] 报告生成失败，原有重试、冷却和账号轮换继续执行。")
            raise

    return await retry_verification(tracked_operation, (Exception,), attempts=attempts,
                                    retry_delay=retry_delay,sleep=sleep,logger=logger,label="账号采集重试")


async def handle_verification_failure(pool, task, account, files, notifier, failure_summary="需要手动验证", *, restricted=True):
    selected = pool.block_and_select(task, account, files)
    previous = Path(account).stem
    until = datetime.fromtimestamp(pool.cooldown_until(account), ZoneInfo('Asia/Shanghai')).strftime('%m月%d日 %H:%M')
    status = "已进入限制状态" if restricted else "采集连续失败，已在本地暂停使用（不代表闲鱼已封禁该账号）"
    category = "账号受限" if restricted else "账号异常"
    cooling = f'{previous} {status}，按配置冷却 {pool.cooldown_seconds / 3600:g} 小时，至 {until}（北京时间）。到期自动恢复候选资格，不强制切回。'
    if selected:
        title = f"[{category}/切换] {previous} → {Path(selected).stem}"
        reason = f"任务：{task}\n触发原因：{failure_summary}\n{cooling}\n下次按原定时间使用 {Path(selected).stem} 检查，尚未确认该账号能正常采集。"
    else:
        title = f"[{category}/无可用账号] {previous}"
        reason = f"任务：{task}\n触发原因：{failure_summary}\n{cooling}\n账号池已无可用账号，停止采集；冷却到期后按原频率重新选择账号。"
    try:
        await notifier({"商品标题": title, "当前售价": "N/A", "商品链接": "#"}, reason)
    except Exception:
        print("账号切换已保存，但通知发送失败。")
    return selected


async def handle_account_success(pool, task, account, notifier, browser=None):
    """Notify once per switch, only after a completed successful scrape attempt.

    A failed Bark delivery stays pending for the next successful scheduled run.
    """
    switch_id = pool.pending_confirmation(task, account)
    if not switch_id:
        return False
    name = Path(account).stem
    suffix = f'（{browser}）' if browser else ''
    try:
        result = await notifier({
            '商品标题': f'[账号运行正常] {name}{suffix}', '当前售价': 'N/A', '商品链接': '#',
        }, f'任务：{task}\n切换后的 {name}{suffix} 已成功完成一轮搜索、筛选和采集。\n即使没有符合条件的新商品，也表示本轮检查正常。检查频率保持不变。')
        if not isinstance(result, dict) or not result.get('bark', {}).get('success'):
            print('账号已运行正常，但 Bark 确认通知未送达；保留到下一次成功检查重试。')
            return False
    except Exception:
        print('账号运行正常确认通知发送失败；保留待通知记录。')
        return False
    pool.acknowledge_confirmation(task, switch_id)
    return True
