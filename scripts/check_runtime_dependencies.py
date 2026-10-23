#!/usr/bin/env python3
"""Fail clearly when BorrowBuddy's shared Python runtime is incomplete.

This is intentionally a preflight only: it never downloads or installs a
package.  A failed check protects a running production server from being
stopped after an ADM Python update has replaced its package area.
"""
import importlib.util
import os
import sys


REQUIRED_MODULES = {
    'Flask': 'flask',
    'Pillow': 'PIL',
    'Gunicorn': 'gunicorn',
}


def module_is_available(module):
    """Return False when an import's parent namespace is missing."""
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def main():
    missing = [name for name, module in REQUIRED_MODULES.items()
               if not module_is_available(module)]
    if not missing:
        print('BorrowBuddy Python runtime is ready.')
        return 0

    requirements = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'requirements.txt',
    )
    print('BorrowBuddy Python runtime is missing: ' + ', '.join(missing), file=sys.stderr)
    print('Restore with:', file=sys.stderr)
    print(f'  {sys.executable} -m pip install --user -r {requirements}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
