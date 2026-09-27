"""Private, single-owner company workspaces. Not a multi-user authorization boundary.

Load the existing runtime in a separate module namespace per company so its
browser, background tasks and closures stay bound to that company's DB/files.
Only the read-only source directory and the inference usage ledger are shared.
"""
import asyncio
import importlib.util
import sys
import time
import uuid
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class NewWorkspace(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspaceDirectory:
    def __init__(self, default):
        self.default = default
        self.runtimes = {'default': default}
        self.apps = {'default': default.app}
        self.stack = None
        self.lock = asyncio.Lock()
        with default.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT,created REAL)')
            fact = c.execute("SELECT value FROM company_facts WHERE field='company.legal_name'").fetchone()
            name = fact['value'] if fact and fact['value'] else 'Your company'
            c.execute('INSERT OR IGNORE INTO workspaces VALUES (?,?,?)', ('default', name[:100], time.time()))

        @asynccontextmanager
        async def lifespan(app):
            async with AsyncExitStack() as stack:
                self.stack = stack
                await stack.enter_async_context(self.apps['default'].router.lifespan_context(self.apps['default']))
                # Watched sources keep running after a restart, even before the
                # owner next opens that company's tab.
                for row in (await self.list())['workspaces']:
                    if row['id'] == 'default':
                        continue
                    if row['id'] in self.apps:
                        child = self.apps[row['id']]
                        await stack.enter_async_context(child.router.lifespan_context(child))
                    else:
                        await self.runtime(row['id'])
                try:
                    yield
                finally:
                    self.stack = None

        self.app = FastAPI(lifespan=lifespan)
        # The directory has exactly the same loopback/origin/write-header policy.
        self.app.middleware('http')(default.local_access)
        self.app.get('/api/workspaces')(self.list)
        self.app.post('/api/workspaces')(self.create)
        self.app.mount('/w', self.dispatch)
        # Existing private API URLs continue to reach the original workspace.
        self.app.mount('/', self.apps['default'])

    async def list(self):
        with self.default.db() as c:
            rows = [dict(row) for row in c.execute('SELECT * FROM workspaces ORDER BY created')]
        return {'workspaces': rows}

    async def create(self, req: NewWorkspace):
        name = req.name.strip()
        if not name:
            raise HTTPException(400, 'Enter a company name.')
        workspace_id = uuid.uuid4().hex
        with self.default.db() as c:
            c.execute('INSERT INTO workspaces VALUES (?,?,?)', (workspace_id, name, time.time()))
        return {'id': workspace_id, 'name': name}

    async def runtime(self, workspace_id):
        async with self.lock:
            if workspace_id in self.apps:
                return self.apps[workspace_id]
            with self.default.db() as c:
                record = c.execute('SELECT * FROM workspaces WHERE id=?', (workspace_id,)).fetchone()
            if not record or len(workspace_id) != 32 or any(ch not in '0123456789abcdef' for ch in workspace_id):
                raise HTTPException(404, 'Workspace not found.')
            if self.stack is None:
                raise HTTPException(503, 'Workspace service is starting. Try again.')
            module_name = 'app._workspace_' + workspace_id
            spec = importlib.util.spec_from_file_location(module_name, self.default.__file__)
            module = importlib.util.module_from_spec(spec)
            module._workspace_data = self.default.DATA / 'companies' / workspace_id
            module._workspace_sources = self.default.SOURCES
            module._workspace_usage_db = self.default.db
            module._workspace_catalog = self.default.CATALOG_DB
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                with module.db() as c:
                    c.execute('INSERT OR IGNORE INTO company_facts(field,value,status,updated) VALUES (?,?,?,?)',
                              ('company.legal_name', record['name'], 'Reported by you', time.time()))
                await self.stack.enter_async_context(module.app.router.lifespan_context(module.app))
            except BaseException:
                sys.modules.pop(module_name, None)
                raise
            self.runtimes[workspace_id] = module
            self.apps[workspace_id] = module.app
            return module.app

    async def dispatch(self, scope, receive, send):
        # /w/{id}/api/... keeps links and old browser tabs permanently scoped.
        from starlette.responses import JSONResponse
        relative = scope['path'][len(scope.get('root_path', '')):]
        parts = relative.strip('/').split('/', 1)
        workspace_id = parts[0]
        if len(parts) != 2 or not parts[1].startswith('api/'):
            await JSONResponse({'detail': 'Workspace endpoint not found.'}, status_code=404)(scope, receive, send)
            return
        try:
            child = await self.runtime(workspace_id)
        except HTTPException as exc:
            await JSONResponse({'detail': exc.detail}, status_code=exc.status_code)(scope, receive, send)
            return
        child_scope = dict(scope, root_path=scope.get('root_path', '') + '/' + workspace_id)
        await child(child_scope, receive, send)
