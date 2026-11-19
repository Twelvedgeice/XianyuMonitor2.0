"""Local deployment entry point with server-side sessions for HTTP and WS."""
import os
import secrets
import time
from pathlib import Path
from http.cookies import SimpleCookie

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.browsers'))
os.environ.setdefault('PYTHONUTF8', '1')

from src.app import app as upstream_app
from starlette.responses import JSONResponse


class LocalSessionGuard:
    def __init__(self, app):
        self.app = app
        self.sessions = {}

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        host = headers.get(b'host', b'').decode()
        if host not in ('127.0.0.1:8765', 'localhost:8765'):
            return await self.reject(scope, receive, send, 403)
        origin = headers.get(b'origin', b'').decode()
        if origin and origin not in ('http://127.0.0.1:8765', 'http://localhost:8765'):
            return await self.reject(scope, receive, send, 403)
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get(b'cookie', b'').decode())
        except Exception:
            return await self.reject(scope, receive, send, 401)
        token = cookies.get('xianyu_local_session')
        token = token.value if token else ''
        now = time.time()
        self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
        path = scope.get('path', '')
        protected = path == '/api' or path.startswith('/api/') or scope['type'] == 'websocket'
        if protected and token not in self.sessions:
            return await self.reject(scope, receive, send, 401)
        if path == '/auth/logout' and scope.get('method') == 'POST':
            self.sessions.pop(token, None)
            response = JSONResponse({'logged_out': True})
            response.delete_cookie('xianyu_local_session', path='/', httponly=True, samesite='strict')
            return await response(scope, receive, send)

        async def send_with_session(message):
            if (path == '/auth/status' and scope.get('method') == 'POST'
                    and message['type'] == 'http.response.start' and message['status'] == 200):
                self.sessions.pop(token, None)
                new_token = secrets.token_urlsafe(32)
                self.sessions[new_token] = time.time() + 43200
                message = dict(message)
                message['headers'] = list(message.get('headers', [])) + [
                    (b'set-cookie', f'xianyu_local_session={new_token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'.encode())
                ]
            await send(message)
        return await self.app(scope, receive, send_with_session)

    async def reject(self, scope, receive, send, status):
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
        else:
            await JSONResponse({'detail': 'Authentication or origin check failed'}, status_code=status)(scope, receive, send)


app = LocalSessionGuard(upstream_app)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8765, log_level='info')
