"""Small local browser UI shared by the standalone agent products.

Each repository vendors this file so it remains independently installable.
"""

from __future__ import annotations

import hmac
import html
import json
import os
import secrets
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

Field = tuple[str, str, str, bool]
Actions = dict[str, list[Field]]


def make_server(
    title: str,
    actions: Actions,
    execute: Callable[[str, dict[str, str]], object],
    *,
    port: int = 8080,
    host: str = "127.0.0.1",
) -> ThreadingHTTPServer:
    """Create a local-only server. The caller owns shutdown and serve_forever."""
    csrf = secrets.token_urlsafe(32)
    access_token = os.environ.get("AGENT_WEB_TOKEN", "")
    if host not in {"127.0.0.1", "localhost", "::1"} and (
        len(access_token) < 16 or access_token.startswith("replace-")
    ):
        raise ValueError("Set a non-example AGENT_WEB_TOKEN of at least 16 characters")
    options = json.dumps(actions).replace("<", "\\u003c")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font:16px system-ui;max-width:760px;margin:3rem auto;padding:0 1rem;color:#172033;background:#f7f9fc}}
main{{background:white;padding:2rem;border-radius:14px;box-shadow:0 6px 24px #10203018}}
label{{display:block;margin-top:1rem;font-weight:600}}input,textarea,select,button{{font:inherit;box-sizing:border-box;width:100%;padding:.65rem;margin-top:.3rem}}
textarea{{min-height:7rem}}button{{margin-top:1.5rem;background:#175cd3;color:white;border:0;border-radius:8px;cursor:pointer}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3fa;padding:1rem;border-radius:8px}}
</style></head><body><main><h1>{html.escape(title)}</h1>
<p>Results are returned as JSON.</p><label for="access-token">Access token (if configured)</label>
<input id="access-token" type="password" autocomplete="off"><label for="action">Action</label>
<select id="action"></select><form id="form"></form><pre id="result" aria-live="polite"></pre>
</main><script>
const actions={options};const csrf={json.dumps(csrf)};
const action=document.getElementById('action'),form=document.getElementById('form'),result=document.getElementById('result');
for(const name of Object.keys(actions)){{const option=document.createElement('option');option.value=name;option.textContent=name;action.appendChild(option)}}
function render(){{form.replaceChildren();for(const [name,label,type,required] of actions[action.value]){{
 const wrapper=document.createElement('label');wrapper.textContent=label;
 const field=document.createElement(type==='textarea'?'textarea':'input');field.name=name;
 if(type!=='textarea')field.type=type;field.required=required;wrapper.appendChild(field);form.appendChild(wrapper)
 }}const button=document.createElement('button');button.textContent='Run';form.appendChild(button)}}
action.onchange=render;render();form.onsubmit=async event=>{{event.preventDefault();result.textContent='Working...';
 const values=Object.fromEntries(new FormData(form));try{{const response=await fetch('/api',{{method:'POST',headers:{{'Content-Type':'application/json','X-CSRF-Token':csrf,'X-Access-Token':document.getElementById('access-token').value}},body:JSON.stringify({{action:action.value,values}})}});
 const data=await response.json();result.textContent=JSON.stringify(data,null,2)}}catch(error){{result.textContent=String(error)}}}};
</script></body></html>""".encode()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, mime: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(200, page, "text/html; charset=utf-8")
            elif self.path == "/healthz":
                self._send(200, b'{"status":"ok"}', "application/json")
            else:
                self._send(404, b'{"error":"not found"}', "application/json")

        def do_POST(self) -> None:
            if self.path != "/api":
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1_000_000:
                    raise ValueError("request size must be between 1 and 1000000 bytes")
                if self.headers.get("X-CSRF-Token") != csrf:
                    raise PermissionError("invalid CSRF token")
                if access_token and not hmac.compare_digest(
                    self.headers.get("X-Access-Token", ""), access_token
                ):
                    raise PermissionError("invalid access token")
                data = json.loads(self.rfile.read(length))
                action, values = data["action"], data["values"]
                if action not in actions or not isinstance(values, dict):
                    raise ValueError("unknown action or invalid fields")
                allowed = {field[0] for field in actions[action]}
                if set(values) - allowed or any(
                    not isinstance(v, str) for v in values.values()
                ):
                    raise ValueError("unknown field or invalid value")
                if any(
                    required and not values.get(name, "").strip()
                    for name, _, _, required in actions[action]
                ):
                    raise ValueError("a required field is empty")
                result = execute(action, values)
                body = json.dumps({"result": result}).encode("utf-8")
                self._send(200, body, "application/json")
            except (
                ValueError,
                KeyError,
                PermissionError,
                RuntimeError,
                TypeError,
            ) as exc:
                body = json.dumps({"error": str(exc)}).encode()
                self._send(400, body, "application/json")
            except Exception as exc:  # noqa: BLE001 - keep handler errors out of HTTP internals
                self.log_error("action failed: %s", type(exc).__name__)
                self._send(500, b'{"error":"action failed"}', "application/json")

    return ThreadingHTTPServer((host, port), Handler)


def serve(
    title: str,
    actions: Actions,
    execute: Callable[[str, dict[str, str]], object],
    *,
    port: int = 8080,
) -> None:
    host = os.environ.get("AGENT_WEB_HOST", "127.0.0.1")
    server = make_server(title, actions, execute, port=port, host=host)
    print(f"{title}: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
