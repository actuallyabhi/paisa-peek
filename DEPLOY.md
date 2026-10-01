# Deploying Paisapeek on your server

Paisapeek runs as three small containers: the **app**, a **scheduler** (push reminders) and **Caddy** (automatic HTTPS). Everything lives in one Docker volume (`data`), which holds the SQLite database, generated keys and backups.

HTTPS is **required**. Phones only install the app and allow notifications over `https://`.

Pick **one** of the two setups:

| | A. Public domain + Caddy | B. Tailscale (private) |
|---|---|---|
| Reachable from | anywhere | only your devices on your tailnet |
| Needs | a domain, ports 80/443 open | Tailscale on the server and phone |
| SMS forwarder works on mobile data | ✅ | ✅ (phone runs Tailscale) |

---

## 0. Server prerequisites

Any Linux box with 1 GB of RAM is plenty (a Raspberry Pi 4, a ₹400/month VPS, an old laptop).

```bash
curl -fsSL https://get.docker.com | sh          # Docker + compose plugin
sudo usermod -aG docker $USER && newgrp docker
```

Get the code onto the server:

```bash
git clone <your-repo-url> paisapeek && cd paisapeek
cp .env.example .env
nano .env
```

In `.env`, set at least:

- `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD`: your login, created on first start. **Use a strong password.**
- `TZ=Asia/Kolkata`, or your own timezone.
- `VAPID_SUBJECT=mailto:you@yourmail.com`: must be real. Apple's push service rejects placeholder addresses.

---

## A. Public domain with automatic HTTPS (Caddy)

1. **DNS:** add an `A` record (and `AAAA` for IPv6), e.g. `paisapeek.example.com` → your server's public IP.
2. **Firewall:** allow inbound TCP **80** and **443** (Caddy needs 80 to get the certificate).
   ```bash
   sudo ufw allow 80,443/tcp
   ```
3. **`.env`:** set `DOMAIN=paisapeek.example.com`. This alone configures allowed hosts, CSRF and secure cookies.
4. **Start:**
   ```bash
   docker compose --profile https up -d --build
   docker compose logs -f caddy      # wait for "certificate obtained successfully", then Ctrl+C
   ```
5. Open `https://paisapeek.example.com` and log in.

The app port stays bound to `127.0.0.1:8089`, so only Caddy can reach it.

## A2. You already run Caddy (or nginx / Traefik)

Use `docker-compose.own-proxy.yml`. It runs only the **app** and the **scheduler** (no second Caddy fighting over ports 80/443). The app listens on `127.0.0.1:8089`; change it with `PORT=` in `.env`.

1. **`.env`:** set `DOMAIN=paisapeek.example.com`. That sets the allowed host, CSRF origin and secure cookies for it.
2. **Start:**
   ```bash
   docker compose -f docker-compose.own-proxy.yml up -d --build
   ```
3. **Add a site to your existing Caddyfile, then reload Caddy** (`sudo systemctl reload caddy`, or `caddy reload`):
   ```
   paisapeek.example.com {
       encode zstd gzip
       reverse_proxy 127.0.0.1:8089
   }
   ```
   Caddy obtains the certificate and passes `X-Forwarded-Proto`, which the app already trusts.

**If your Caddy itself runs in Docker,** `127.0.0.1` inside the Caddy container is Caddy, not your server. Use one of these:
- **Simplest:** give the Caddy container `extra_hosts: ["host.docker.internal:host-gateway"]` and use `reverse_proxy host.docker.internal:8089`. Bind the app with `BIND=172.17.0.1` (the Docker bridge) or `BIND=0.0.0.0` behind a firewall, because Caddy can't reach `127.0.0.1` from inside its container.
- **Or** put both on one Docker network: add `networks: [caddy]` to the `app` service (with `networks: {caddy: {external: true}}` at the bottom) and use `reverse_proxy app:8000`.

Switching between `docker-compose.yml` and this file is safe: both use the same `data` volume. Don't run both at once.

## B. Private, over Tailscale

1. Install Tailscale on the server (`curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`) and on your phone.
2. In the Tailscale admin console, enable **MagicDNS** and **HTTPS certificates**.
3. **`.env`:** leave `DOMAIN=` empty and set:
   ```
   CSRF_TRUSTED_ORIGINS=https://<server>.<tailnet>.ts.net
   ALLOWED_HOSTS=<server>.<tailnet>.ts.net,localhost
   ```
4. **Start the app** (no Caddy), then publish it on your tailnet with HTTPS:
   ```bash
   docker compose up -d --build
   sudo tailscale serve --bg 8089
   ```
5. Open `https://<server>.<tailnet>.ts.net` on any device in your tailnet.

---

## 1. On your phone

- **Install:**
  - Android (Chrome): open the site, then ⋮ → **Install app**.
  - iPhone (Safari): **Share → Add to Home Screen**.
- **Notifications:** open the app from its icon → **More → Notifications → Enable on this device → Send a test**. Then choose the daily "log today" time and the reminder time for bills and card statements.
- **Accounts:** add your savings account, cards and cash; set one as **default**. For each credit card, set the **statement day** and **due day** so reminders arrive on those dates.
- **SMS auto-capture** (Android, optional): install the Paisapeek APK from [GitHub Releases](https://github.com/actuallyabhi/paisa-peek/releases) and paste the URL shown under **More → SMS auto-capture** ([details](android/README.md)). You can also use a forwarder app (*SMS to URL Forwarder*, MacroDroid or Tasker) pointed at that URL and filtered to your banks' sender IDs.

## 2. Backups

- **From the app:** **More → Backup & restore → Export full backup**. Keep a copy off the server.
- **Automatic nightly backups:** this writes to the `data` volume and keeps the last 14.
  ```bash
  crontab -e
  # add this line (adjust the path):
  30 2 * * * cd /home/you/paisapeek && docker compose exec -T app python manage.py backup --keep 14
  # setup A2: docker compose -f docker-compose.own-proxy.yml exec -T app python manage.py backup --keep 14
  ```
  Copy them off the machine now and then:
  ```bash
  docker compose cp app:/data/backups ./backups
  ```
- **Restoring on a new server:** deploy as above, then use the **Namaste** screen → *Restore from backup*.

## 3. Updating

```bash
cd paisapeek && git pull
docker compose --profile https up -d --build      # setup A
docker compose -f docker-compose.own-proxy.yml up -d --build   # setup A2 (your own Caddy)
```

Database migrations run automatically on start. Take a backup first if it's a big update.

## 4. Optional: smarter Ramble with a local LLM

Needs about 6 GB of RAM for a 7B model.

1. Start Ollama and download a model:
   ```bash
   docker compose --profile llm up -d
   docker compose exec ollama ollama pull qwen2.5:7b
   ```
2. Add to `.env`:
   ```
   LLM_BASE_URL=http://ollama:11434/v1
   LLM_MODEL=qwen2.5:7b
   ```
3. Restart the app:
   ```bash
   docker compose up -d
   ```

You can also point `LLM_BASE_URL`/`LLM_API_KEY` at any OpenAI-compatible API instead.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "CSRF verification failed" on login | `DOMAIN`, or `CSRF_TRUSTED_ORIGINS`, doesn't exactly match the `https://…` address in your browser. |
| No "Install app" option | You're not on `https://`, or the page was opened by IP instead of the domain. |
| Notifications never arrive | Check `docker compose logs scheduler`, confirm `VAPID_SUBJECT` is a real address, and on iPhone open the app from the Home Screen icon. |
| Caddy can't get a certificate | DNS isn't pointing at the server yet, or port 80 is blocked. |
| Caddy log: `challenge failed` against an IP that isn't your server | The domain in your Caddyfile doesn't point at this server, or it's still a placeholder. Use your real domain, set its DNS **A record** to the server's public IP, and forward ports 80/443 if it's a home server. |
| Firefox `SSL_ERROR_INTERNAL_ERROR_ALERT` / Chrome `ERR_SSL_PROTOCOL_ERROR` | Caddy has no certificate for the name you opened. Use the exact domain (not the IP), check `journalctl -u caddy` (or `docker logs caddy`) for "challenge failed", make sure ports 80/443 are open, and on Cloudflare use SSL mode **Full (strict)** or "DNS only". Never run the bundled Caddy (`--profile https`) alongside your own. |
| Forgot password | `docker compose exec app python manage.py changepassword admin` |
