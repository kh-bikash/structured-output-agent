"""Authenticated Vercel entry point for Structured Output Agent."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field

from structured_output_agent.__main__ import WEB_ACTIONS, execute
from structured_output_agent.engine import OutputValidationError

app = FastAPI(title="Structured Output Agent", docs_url=None, redoc_url=None)
MAX_BODY = 100_000


def _supabase_config() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get(
        "SUPABASE_ANON_KEY", ""
    )
    if not url.startswith("https://") or not key:
        raise RuntimeError("Supabase authentication is not configured")
    return url, key


def _auth_request(
    method: str, path: str, *, token: str = "", body: dict | None = None
) -> dict:
    url, key = _supabase_config()
    headers = {"apikey": key, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.request(
                method, f"{url}/auth/v1/{path}", headers=headers, json=body
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, "Authentication service unavailable") from exc
    if response.status_code >= 400:
        if response.status_code in (400, 401, 422):
            raise HTTPException(401, "Invalid credentials or expired session")
        if response.status_code == 429:
            raise HTTPException(429, "Too many authentication attempts")
        raise HTTPException(503, "Authentication service unavailable")
    if not response.content:
        return {}
    return response.json()


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    parsed = urlparse(origin)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if parsed.netloc != host or (parsed.scheme != "https" and not local):
        raise HTTPException(403, "Invalid origin")


def _set_session(response: Response, session: dict) -> None:
    access = session.get("access_token")
    refresh = session.get("refresh_token")
    if not access or not refresh:
        raise HTTPException(503, "Authentication session unavailable")
    expires = min(max(int(session.get("expires_in", 3600)), 60), 86400)
    response.set_cookie(
        "agent_access",
        access,
        max_age=expires,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "agent_refresh",
        refresh,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _user(request: Request) -> dict:
    token = request.cookies.get("agent_access", "")
    if not token:
        raise HTTPException(401, "Sign in required")
    user = _auth_request("GET", "user", token=token)
    if not user.get("id"):
        raise HTTPException(401, "Invalid session")
    return user


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ActionRequest(BaseModel):
    action: str
    values: dict[str, str]


@app.middleware("http")
async def request_limits(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        try:
            _same_origin(request)
        except HTTPException:
            return JSONResponse({"detail": "Invalid origin"}, status_code=403)
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or int(length) > MAX_BODY):
            return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


@app.get("/healthz")
def healthz():
    _supabase_config()
    return {"status": "ok"}


@app.get("/api/session")
def session(request: Request):
    user = _user(request)
    return {"email": user.get("email"), "id": user["id"]}


@app.post("/auth/signup")
def signup(credentials: Credentials):
    _auth_request("POST", "signup", body=credentials.model_dump())
    return {"message": "Check your email to confirm your account, then sign in."}


@app.post("/auth/login")
def login(credentials: Credentials):
    session = _auth_request(
        "POST", "token?grant_type=password", body=credentials.model_dump()
    )
    response = JSONResponse({"message": "Signed in"})
    _set_session(response, session)
    return response


@app.post("/auth/refresh")
def refresh(request: Request):
    token = request.cookies.get("agent_refresh", "")
    if not token:
        raise HTTPException(401, "Sign in required")
    session = _auth_request(
        "POST", "token?grant_type=refresh_token", body={"refresh_token": token}
    )
    response = JSONResponse({"message": "Session refreshed"})
    _set_session(response, session)
    return response


@app.post("/auth/logout")
def logout(request: Request):
    token = request.cookies.get("agent_access", "")
    if token:
        try:
            _auth_request("POST", "logout", token=token)
        except HTTPException:
            pass
    response = JSONResponse({"message": "Signed out"})
    response.delete_cookie("agent_access", path="/")
    response.delete_cookie("agent_refresh", path="/")
    return response


@app.post("/api/action")
def action(request: Request, payload: ActionRequest):
    _user(request)
    if payload.action not in WEB_ACTIONS:
        raise HTTPException(400, "Unknown action")
    fields = WEB_ACTIONS[payload.action]
    allowed = {field[0] for field in fields}
    if set(payload.values) - allowed:
        raise HTTPException(400, "Unknown field")
    if any(
        required and not payload.values.get(name, "").strip()
        for name, _, _, required in fields
    ):
        raise HTTPException(400, "A required field is empty")
    if any(len(value) > 20_000 for value in payload.values.values()):
        raise HTTPException(413, "Field too large")
    try:
        return {"result": execute(payload.action, payload.values)}
    except (HTTPError, URLError, TimeoutError) as exc:
        raise HTTPException(503, "Model provider unavailable") from exc
    except (ValueError, RuntimeError, KeyError, OutputValidationError) as exc:
        raise HTTPException(400, str(exc)[:500]) from exc


@app.get("/", response_class=HTMLResponse)
def home():
    actions = json.dumps(WEB_ACTIONS).replace("<", "\\u003c")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Structured Output Agent</title><link rel="stylesheet" href="/site.css"></head><body><main><h1>Structured Output Agent</h1><p>Extract typed data from text or validate JSON against a schema.</p><section id="auth"><h2>Account</h2><form id="credentials"><label>Email<input name="email" type="email" autocomplete="email" required></label><label>Password<input name="password" type="password" autocomplete="current-password" minlength="8" required></label><div class="row"><button type="button" id="login">Sign in</button><button type="button" id="signup">Create account</button><button type="button" id="logout">Sign out</button></div><p id="account"></p></form></section><section><h2>Work area</h2><label>Action<select id="action"></select></label><form id="form"></form><pre id="result" aria-live="polite"></pre></section></main><script id="actions" type="application/json">{actions}</script><script src="/site.js" defer></script></body></html>"""


@app.get("/site.css")
def css():
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        "body{font:16px system-ui;background:#f5f7fb;color:#172033;max-width:760px;margin:2rem auto;padding:0 1rem}main{display:grid;gap:1.5rem}section{background:white;padding:1.5rem;border-radius:12px;box-shadow:0 4px 18px #1232}label{display:block;margin:.8rem 0;font-weight:600}input,textarea,select,button{font:inherit;box-sizing:border-box;width:100%;padding:.65rem;margin:.25rem 0}textarea{min-height:7rem}.row{display:flex;gap:.5rem}.row button{width:auto}button{background:#175cd3;color:white;border:0;border-radius:8px;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eaf0f8;padding:1rem}",
        media_type="text/css",
    )


@app.get("/site.js")
def javascript():
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        r"""const actions=JSON.parse(document.querySelector('#actions').textContent);const action=document.querySelector('#action'),form=document.querySelector('#form'),result=document.querySelector('#result'),account=document.querySelector('#account');for(const name of Object.keys(actions)){const option=document.createElement('option');option.value=name;option.textContent=name;action.appendChild(option)}function render(){form.replaceChildren();for(const [name,label,type,required] of actions[action.value]){const wrapper=document.createElement('label');wrapper.textContent=label;const field=document.createElement(type==='textarea'?'textarea':'input');field.name=name;if(type!=='textarea')field.type=type;field.required=required;wrapper.appendChild(field);form.appendChild(wrapper)}const button=document.createElement('button');button.textContent='Run';form.appendChild(button)}action.onchange=render;render();async function post(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.detail||'Request failed');return data}async function status(){let response=await fetch('/api/session');if(response.status===401){try{await post('/auth/refresh',{});response=await fetch('/api/session')}catch{}}account.textContent=response.ok?'Signed in as '+(await response.json()).email:'Sign in to run actions'}status();for(const name of ['login','signup'])document.querySelector('#'+name).onclick=async()=>{const credentials=Object.fromEntries(new FormData(document.querySelector('#credentials')));try{const data=await post('/auth/'+name,credentials);account.textContent=data.message;if(name==='login')status()}catch(error){account.textContent=error.message}};document.querySelector('#logout').onclick=async()=>{await post('/auth/logout',{});status()};form.onsubmit=async event=>{event.preventDefault();result.textContent='Working...';try{const data=await post('/api/action',{action:action.value,values:Object.fromEntries(new FormData(form))});result.textContent=JSON.stringify(data.result,null,2)}catch(error){result.textContent=error.message}};
""",
        media_type="application/javascript",
    )
