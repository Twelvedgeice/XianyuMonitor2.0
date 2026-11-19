"""Targeted Windows Firefox rendering preference, applied before startup."""
import re
import sys

OCCLUSION_PREF = 'widget.windows.window_occlusion_tracking.enabled'


def prepare_background_rendering(account, profile):
    if account != 'private_3' or sys.platform != 'win32':
        return False
    target = profile / 'profile' / 'user.js'
    content = target.read_bytes().decode('utf-8') if target.exists() else ''
    values = re.findall(
        r'^\s*user_pref\(\s*[\"\']' + re.escape(OCCLUSION_PREF) +
        r'[\"\']\s*,\s*(true|false)\s*\)\s*;', content, re.MULTILINE)
    if values and values[-1] == 'false':
        return False
    # Juggler applies firefox_user_prefs only AFTER its startup-idle wait.
    # user.js is read before that wait, and preserves other profile settings.
    # Mozilla remote-protocol precedent: bug 1802473.
    addition = ('\n// private3 automation: keep rendering when its window is covered.\n'
                f'user_pref("{OCCLUSION_PREF}", false);\n')
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name('user.js.private3-pending')
    pending.write_bytes((content + addition).encode('utf-8'))
    pending.replace(target)
    return True
