# Deployment

## Local product

Install with `python -m pip install -e .`, then run the command shown in README. The browser binds to `127.0.0.1:8080` by default. `GET /healthz` is a lightweight health endpoint.

## Container

Copy `.env.example` to `.env`, replace every example secret, and keep that file outside Git. Build and run from this repository:

```bash
docker build -t structured-output-agent .
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env structured-output-agent serve --port 8080
```

The image runs as a non-root user. It binds inside the container to `0.0.0.0`; the example publishes only to host loopback. A non-loopback bind requires `AGENT_WEB_TOKEN` of at least 16 characters. The browser asks for that token and sends it to the action endpoint. Put TLS and an authenticated reverse proxy in front of any public deployment.

This product is stateless. Set OPENAI_API_KEY to enable extraction; validation works without it.

## Release checks

Run `ruff check src tests`, `ruff format --check src tests`, and `pytest -q`. Test the browser action path and `/healthz` after deployment. Keep secrets in the deployment platform, monitor failed actions and model/provider errors, and set backups for any mounted data volume.
