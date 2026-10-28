# Site limits

Per-user, per-site speed limits: a user gets full speed for some sites (Instagram, YouTube, …)
up to a daily quota, then a slow speed for those sites only. Everything else stays at full speed.
Usage resets every day at 00:00 in `SITE_LIMIT_TIMEZONE`. A limit can be "today only" (removed
at 00:00), last N days, or stay forever.

Dashboard: Users → ⋮ → **Site limits**. API: `/api/user/{id}/site-limits`.

## How it works

- The panel adds two SOCKS outbounds per limit (`sl-<id>-full`, `sl-<id>-slow`) and a routing
  rule (`user` + `domain`) to the Xray config it sends to nodes (`app/core/site_limits.py`).
- Both outbounds point to `pg-site-limiter` on the node. The SOCKS username carries the limit id
  and speed, and all of a limit's connections share one token bucket, so switching to slow also
  slows connections that are already open.
- Traffic is counted from the outbounds' stats in the node-usage job (every 30 s by default).
  When a limit crosses its quota, the panel switches the routing rule. Nodes apply that without
  restarting Xray.
- UDP to limited domains is dropped so QUIC falls back to TCP through the limiter.
- Domain matching needs `sniffing` enabled on inbounds.

## Install the limiter on a node

Each node host needs the limiter on `127.0.0.1:10808`:

```sh
cd limiter
docker run --rm -v "$PWD":/src -w /src -e CGO_ENABLED=0 golang:1.23-alpine \
  go build -trimpath -ldflags="-s -w" -o pg-site-limiter .
install -m755 pg-site-limiter /usr/local/bin/
cp pg-site-limiter.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now pg-site-limiter
```

Without it, traffic for limited sites fails on that node. With several nodes, the quota is
global (counted by the panel), and each node's limiter enforces the slow speed separately.

## Settings (.env)

| Variable | Default | |
|---|---|---|
| `SITE_LIMIT_TIMEZONE` | `UTC` | Day boundary for the daily reset, e.g. `Asia/Tehran` |
| `SITE_LIMITER_ADDRESS` | `127.0.0.1` | Limiter address as seen from the node |
| `SITE_LIMITER_PORT` | `10808` | Limiter port |

## Rebuild the panel image

```sh
cd dashboard && docker run --rm -v "$PWD":/app -w /app oven/bun:1.3 \
  sh -c 'bun install --frozen-lockfile && VITE_BASE_API=/ bun run build && cp build/index.html build/404.html'
cd .. && docker build -t pasarguard-custom:latest . && cd /opt/pasarguard && docker compose up -d
```
