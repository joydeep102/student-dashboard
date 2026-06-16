# Fighter Bull's — Student Portal for Online Trading Courses

A Django portal for delivering online courses with:

- **Admin-created student accounts** — no public signup; staff create and enroll students from the Django admin.
- **Live classes over Google Meet** — Meet links are **auto-generated** via the Google Calendar API when a class is scheduled.
- **Recorded lessons played in-portal** — videos are uploaded to YouTube as **Unlisted** and played through a **branded custom player** with no YouTube logo, title bar, share buttons, or `youtube.com` links visible. The video ID is served from an auth-gated endpoint, not embedded in the page HTML.

---

## Run with Docker (recommended)

Runs the app with **PostgreSQL + Gunicorn + WhiteNoise** (static files) — no
local Python setup needed.

```bash
# 0. clone
git clone git@github.com:joydeep102/student-dashboard.git
cd student-dashboard

# 1. (optional) copy env defaults and edit secrets
cp .env.example .env        # then set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, hosts

# 2. build + start (SEED_DEMO=1 loads demo data on first boot)
SEED_DEMO=1 docker compose up -d --build

# 3. open the app  (host port 6262 -> container 8000)
#    http://127.0.0.1:6262/accounts/login/   (admin / admin12345)
```

The entrypoint waits for the database, runs migrations, collects static, and
optionally seeds demo data, then starts Gunicorn. Useful commands:

```bash
docker compose logs -f web          # tail logs
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo
docker compose down                 # stop (keeps the db/media volumes)
```

Notes:
- Local dev (without Docker) still uses **SQLite**; Docker uses **PostgreSQL**
  automatically (settings switch on the `POSTGRES_DB` env var).
- `secrets/` (Google OAuth client + cached tokens) is mounted as a volume, so
  it's never baked into the image. Run the one-time `google_auth` / `youtube_auth`
  browser flows on a machine with a browser, then copy the generated token files
  into `secrets/`.
- For production: set a real `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`,
  `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and put it behind HTTPS
  (e.g. a reverse proxy / load balancer).

## Run locally without Docker

```powershell
# 1. Install dependencies (already installed if you used the setup)
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Apply database migrations
.\venv\Scripts\python.exe manage.py migrate

# 3. (Optional) Load demo data — admin, students, a course, lessons, live classes
.\venv\Scripts\python.exe manage.py seed_demo

# 4. Run the server
.\venv\Scripts\python.exe manage.py runserver
```

Open <http://127.0.0.1:8000/accounts/login/>.

### Demo logins (after `seed_demo`)

> Login is by **email address** (not username).

| Role    | Email (login)            | Password       | Plan in Batch 01 |
|---------|--------------------------|----------------|------------------|
| Admin   | `admin@example.com`      | `admin12345`   | —                |
| Trainer | `instructor1@example.com`| `trainer12345` | —                |
| Student | `student1@example.com`   | `student12345` | Basic (L1)       |
| Student | `student3@example.com`   | `student12345` | Advance (L2)     |
| Student | `student2@example.com`   | `student12345` | Pro Trader (L3)  |
| Student | `student4@example.com`   | `student12345` | Elite (L4)       |

> Log in as each one to see the tier gating: `student1` (Basic) has most content
> locked with "Upgrade" prompts, while `student4` (Elite) sees everything.
> Change these before any real use. Create your own superuser with
> `python manage.py createsuperuser`.

---

## Batches & plan tiers (how access works)

Courses are delivered **batch by batch**. Each batch holds students on different
**plans** (Basic / Advance / Pro Trader / Elite). Every plan has a **level**
(Basic = 1 … Elite = 4). Each live class and recorded video can require a
minimum plan. A student can open a piece of content only when:

1. they have an active enrollment in that content's **batch**, AND
2. their **plan level ≥ the content's required plan level**
   (content with no required plan is open to everyone in the batch).

So a Basic student's classes "end" once the batch moves into higher-tier
content, while upgraded students continue. Lower-plan students see locked
content with an **Upgrade to unlock** prompt; the video/Meet endpoints are
also enforced server-side, so locked content can't be opened directly.

## How admins manage everything

Everything is done from the Django admin at **`/admin/`**:

- **Plans** → *Courses → Plans*. The 4 tiers (price, duration, level, features for the pricing page). Seeded for you.
- **Create a student** → *Accounts → Users → Add*. Set role = Student + a password. Enroll them into a batch on a plan from the inline at the bottom of the user page.
- **Create a batch** → *Courses → Batches → Add*. Pick its course, then add students (with their plan), video lessons, and live classes — all inline. For each video/class set its **required plan** (blank = everyone in the batch).
- **Recorded videos** → paste the **YouTube video ID** of your unlisted upload (the 11-char ID, not the full URL) and choose the required plan.
- **Schedule a live class** → leave the Meet link blank to auto-generate one (see below), or paste a link manually; set the required plan to control who can join.
- **Pricing page** at **`/pricing/`** is built automatically from your active Plans.

---

## Recorded videos — how the "no YouTube" part works

1. Upload each lesson video to YouTube and set its visibility to **Unlisted**.
2. Copy the video ID (e.g. for `https://youtu.be/aqz-KE-bpKQ` the ID is `aqz-KE-bpKQ`) into the lesson's **YouTube ID** field.
3. Students watch on the lesson page through a **custom player** that:
   - disables native YouTube controls (`controls=0`) and uses our own control bar (play/seek/volume/speed/fullscreen),
   - hides branding (`modestbranding`, `rel=0`, no title/share via a top mask + click shield),
   - fetches the video ID from an **auth + enrollment-gated** endpoint, so it isn't sitting in the page source.

**Honest limitation:** the actual video bytes still stream from YouTube's servers, so a determined technical user inspecting network traffic could discover the source. This approach hides YouTube from normal students and keeps videos unlisted/private. If you need videos that *never* touch youtube.com, self-host them (S3/Cloudflare Stream/Bunny) — the `Lesson` model can be extended for that.

---

## Live classes — Google Meet auto-generation

Out of the box, the portal runs fine and you can paste Meet links manually. To
**auto-generate** them:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Google Calendar API**.
2. Create an **OAuth client ID** of type *Desktop app*, download the JSON, and save it to `secrets/client_secret.json`.
3. Authorize once (opens a browser):

   ```powershell
   .\venv\Scripts\python.exe manage.py google_auth
   ```

   This caches `secrets/token.json`. From then on, saving a live class with a
   blank link creates a Google Calendar event and stores its Meet link
   automatically. Deleting the class removes the calendar event.

The authorizing Google account hosts the events (configurable via
`GOOGLE_CALENDAR_ID`). Students never see the raw link in listings — they reach
Meet through a gated `/classroom/live/<id>/join/` redirect that only works from
10 minutes before start until the class ends.

---

## Trainers — upload videos for admin approval → YouTube

Instructors get a **Trainer Studio** at **`/trainer/`** (link appears in the top
nav for instructor accounts). There they:

1. **Upload** a class recording (video file) targeted at a batch, with an optional minimum plan.
2. The submission goes into a **pending queue**; nothing is published yet.

Admins review submissions under *Trainers → Video submissions* (or via the
**"Videos awaiting your approval"** panel on the admin home). Selecting one and
running **"✅ Approve & publish to YouTube"** will:

- upload the file to YouTube as **unlisted** via the YouTube Data API, then
- create a **recorded class (Lesson)** in the target batch with that video ID.

If YouTube isn't authorized yet, the admin can instead **paste a YouTube ID**
into the submission and approve — it publishes without uploading.

**Enable auto-upload (one time):** enable the *YouTube Data API v3* on the same
Google Cloud project as your OAuth client, then:

```powershell
.\venv\Scripts\python.exe manage.py youtube_auth
```

This caches `secrets/youtube_token.json`. Demo trainer login (after `seed_demo`):
`instructor1` / `trainer12345`.

> Note: approval uploads the file synchronously, which is fine for typical class
> recordings. For very large files or high volume, move the upload to a
> background worker (Celery/RQ) later — the upload service is already isolated
> in `trainers/youtube.py`.

## Weekly schedule & trainers conducting live classes

The **admin decides which weekday(s)** a batch runs its live class: on the Batch
admin page, add **"Weekly class days"** (e.g. Mon / Wed / Fri at 7:00 PM, each
with an optional minimum plan). Students see these days on the batch page.

**Trainers** (the instructor assigned to that batch's course) open **Trainer
Studio → 🔴 Live classes** (`/trainer/live/`). For each batch they teach they see
the weekly schedule, and **only on a scheduled weekday** a "▶ Start … class"
button appears. Starting it:

- creates a live `LiveClass` for the batch (auto-generating the Google Meet link
  if Google is connected, or the trainer can paste a Meet link), and
- immediately shows it as **LIVE** on students' dashboards with a Join button.

The trainer can **End class** when finished. Trying to start a class on a
non-scheduled day is rejected. A trainer can only conduct batches whose course
they're set as the instructor of.

## Login: show-password + Sign in with Google

The login page has a **👁 show/hide password** toggle, and — when configured — a
**Continue with Google** button.

**Google login** uses a web OAuth2 flow and logs in the **existing, active user
whose `email` matches the verified Google email** (no auto-signup — accounts are
admin-created). So set each user's **email to their Google address** in the
admin for this to work.

Configure with a git-ignored `secrets/google_login.json` (or `GOOGLE_CLIENT_ID`
/ `GOOGLE_CLIENT_SECRET` env vars):

```json
{ "client_id": "...", "client_secret": "...",
  "redirect_uri": "http://127.0.0.1:8000/accounts/google/callback/" }
```

In Google Cloud Console (Web OAuth client) add these **Authorized redirect URIs**:

```
http://127.0.0.1:8000/accounts/google/callback/
http://localhost:8000/accounts/google/callback/
https://YOUR-DOMAIN/accounts/google/callback/   # production (HTTPS)
```

> Keep `secrets/google_login.json` out of git (it already is). Rotate the client
> secret if it's ever exposed.

## Project layout

```
config/        Django project settings & root URLs
accounts/      Custom User model (roles), admin student-creation, auth pages
courses/       Course, Enrollment, Lesson models; student dashboard & player views
classroom/     LiveClass model + Google Meet/Calendar integration + management command
templates/     HTML (base, auth, dashboard, course, lesson/player, waiting room)
static/        CSS + the branded player JavaScript (static/js/player.js)
secrets/       Google OAuth client secret & cached token (git-ignored)
```

---

## Connect Google (Calendar + YouTube) from the admin — recommended

Instead of the Desktop-client `google_auth` / `youtube_auth` commands (which need
a browser on the server), you can connect both from the **admin home** using the
same web OAuth client as "Sign in with Google":

1. Make sure the login client is configured (`secrets/google_login.json` or the
   `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` env vars), and its
   `redirect_uri` is your production callback
   (`https://YOUR-DOMAIN/accounts/google/callback/`), registered in the Console.
2. In the Google Cloud Console, **enable the Calendar API and YouTube Data API
   v3**, and add the scopes `…/auth/calendar.events` and `…/auth/youtube.upload`
   to the OAuth consent screen. While the app is in *Testing*, add the admin's
   Google account as a **test user**.
3. Log in to `/admin/` as an admin → **Google connections** panel →
   **Calendar / Meet** and **YouTube**. Each opens a Google consent screen
   (offline access, so a refresh token is stored) and caches its token
   (`secrets/token.json`, `secrets/youtube_token.json`). The panel then shows
   **connected ✓**.

> For **YouTube**, sign in with the Google account that owns the target channel
> so uploads land there. The connect links are admin-only.

## Troubleshooting

### "Sign in with Google" — `Error 400: redirect_uri_mismatch`
The app sends the redirect URI from `secrets/google_login.json` (or the
`GOOGLE_LOGIN_REDIRECT_URI` env var) to Google, and it must match an
**Authorized redirect URI** on the OAuth **Web** client *exactly* (scheme, host,
path, trailing slash). For production set it to your real domain:

```json
{ "client_id": "…", "client_secret": "…",
  "redirect_uri": "https://YOUR-DOMAIN/accounts/google/callback/" }
```

Then add that same URL under *APIs & Services → Credentials → (your Web client)
→ Authorized redirect URIs* in the Google Cloud Console. `secrets/` is a mounted
volume, so after editing the JSON just `docker compose restart web`.

### "Google sign-in failed. Please try again." (after the consent screen)
This is the server-side token exchange failing. The app sets
`OAUTHLIB_RELAX_TOKEN_SCOPE=1` so Google adding the `openid` scope doesn't break
the exchange, and logs the real cause. If it still fails, check the traceback:

```bash
docker compose logs --tail=60 web      # look for "token exchange failed"
```

Behind an HTTPS reverse proxy, make sure it forwards `X-Forwarded-Proto: https`
(the callback is built from the configured https redirect URI).

### Trainer can't start a live class
The trainer's **▶ Start class** button only appears on a batch's **scheduled
weekday** (admin sets these under *Batch → Weekly class days*). On any other day
the console shows "No class scheduled for today" — this is by design. Add a
schedule slot for the desired weekday in the admin to enable it. Note that
without Google connected, no Meet link is auto-generated — the trainer pastes one
into the optional field when starting the class.

### `docker compose … : no configuration file provided: not found`
You're not in the project directory. `cd` to the folder containing
`docker-compose.yml` first, or pass `-f /path/to/docker-compose.yml`.

## Going to production (checklist)

- Set `DJANGO_DEBUG=False`, a real `DJANGO_SECRET_KEY`, and `DJANGO_ALLOWED_HOSTS` (env vars).
- Switch the database from SQLite to MySQL/PostgreSQL in `config/settings.py`.
- Run `python manage.py collectstatic` and serve static/media via your web server or a CDN.
- Serve over HTTPS (required for Google OAuth redirect and secure cookies).
- Set `DJANGO_CSRF_TRUSTED_ORIGINS` to your domain(s).
```
