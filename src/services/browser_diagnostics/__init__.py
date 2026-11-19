"""Compatibility bridge to the independent local browser diagnostics project."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
PROJECT_CONFIG = ROOT / 'data/browser-diagnostics-project.json'


def project_module():
    config = json.loads(PROJECT_CONFIG.read_text(encoding='utf-8-sig'))
    entry = Path(config['project_root']).resolve() / 'browser_diagnostics/__init__.py'
    key = '_local_browser_diagnostics_project'
    existing = sys.modules.get(key)
    if existing is not None and Path(existing.__file__).resolve() == entry:
        return existing
    spec = importlib.util.spec_from_file_location(key, entry)
    if spec is None or spec.loader is None:
        raise ImportError('Independent browser diagnostics project is unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[key] = module
    return module


def classify(error):
    return project_module().classify(error)


def create_report(account_path, errors=(), *, task=None, root=None, trigger='manual'):
    monitor = Path(root) if root is not None else ROOT
    return project_module().create_report(account_path, errors, task=task, root=monitor,
                                         trigger=trigger)


async def diagnose_failure(account, errors, *, task=None):
    return await asyncio.wait_for(asyncio.to_thread(
        create_report, account, errors, task=task, trigger='two_consecutive_failures'), timeout=5)
