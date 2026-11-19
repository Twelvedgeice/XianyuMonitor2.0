"""Manual local snapshot: python -m src.services.browser_diagnostics --account private_3."""
import argparse
from pathlib import Path
from . import create_report


def main():
    parser = argparse.ArgumentParser(description='浏览器节点只读诊断，不启动浏览器或搜索闲鱼')
    parser.add_argument('--account', required=True, choices=('private1', 'private_2', 'private_3'))
    args = parser.parse_args()
    print(create_report(Path('state') / (args.account + '.json')))


if __name__ == '__main__':
    main()
