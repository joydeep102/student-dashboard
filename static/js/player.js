/*
 * Branded in-portal video player.
 *
 * Loads an (unlisted) YouTube video through the IFrame API with the native
 * controls disabled (controls=0, modestbranding, rel=0, fs=0, disablekb) and
 * drives playback with our own control bar. The video ID is fetched from an
 * auth-gated endpoint (not embedded in the page HTML), and a transparent
 * shield + top mask block any residual YouTube links/branding.
 *
 * The element <div id="vplayer" data-source-url="..."> bootstraps everything.
 */
(function () {
    const root = document.getElementById("vplayer");
    if (!root) return;

    const sourceUrl = root.dataset.sourceUrl;
    const progressUrl = root.dataset.progressUrl;
    const csrf = root.dataset.csrf;
    const resumeAt = parseFloat(root.dataset.resume || "0") || 0;
    let player = null;
    let progressTimer = null;

    // --- Watch-progress reporting (Udemy-style resume + completion) ---------
    let completed = root.dataset.completed === "1";
    let lastSavedPos = -1;
    let saving = false;
    let resumed = false;

    // Persist the current position (and completion) to the server. Throttled by
    // the caller; only fires when there's a real change to record.
    function saveProgress(position, markComplete) {
        if (!progressUrl || saving) return;
        position = Math.max(0, Math.floor(position || 0));
        const willComplete = markComplete && !completed;
        if (!willComplete && Math.abs(position - lastSavedPos) < 5) return;
        saving = true;
        const body = new URLSearchParams({ position: String(position) });
        if (willComplete) body.set("completed", "1");
        fetch(progressUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrf || "",
                "X-Requested-With": "fetch",
            },
            body: body.toString(),
        })
            .then((res) => (res.ok ? res.json() : null))
            .then((data) => {
                if (data && data.completed) completed = true;
                lastSavedPos = position;
            })
            .catch(() => {})
            .finally(() => { saving = false; });
    }

    // 1) Load the IFrame API script once.
    function loadApi() {
        return new Promise((resolve) => {
            if (window.YT && window.YT.Player) return resolve();
            const prev = window.onYouTubeIframeAPIReady;
            window.onYouTubeIframeAPIReady = function () {
                if (prev) prev();
                resolve();
            };
            const tag = document.createElement("script");
            tag.src = "https://www.youtube.com/iframe_api";
            document.head.appendChild(tag);
        });
    }

    // 2) Fetch the video id from our server (kept out of page source).
    async function fetchSource() {
        const res = await fetch(sourceUrl, { headers: { "X-Requested-With": "fetch" } });
        if (!res.ok) throw new Error("source unavailable");
        return res.json();
    }

    function fmt(t) {
        t = Math.max(0, Math.floor(t || 0));
        const s = t % 60, m = Math.floor(t / 60) % 60, h = Math.floor(t / 3600);
        const pad = (n) => String(n).padStart(2, "0");
        return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
    }

    function buildShell() {
        root.innerHTML = `
            <div id="yt-frame"></div>
            <div class="top-mask"></div>
            <div class="click-shield" id="shield"></div>
            <div class="center-btn" id="centerBtn"><button title="Play">▶</button></div>
            <div class="controls">
                <button id="playBtn" title="Play/Pause">▶</button>
                <span class="time" id="cur">0:00</span>
                <input type="range" class="seek" id="seek" value="0" min="0" max="100" step="0.1">
                <span class="time" id="dur">0:00</span>
                <button id="muteBtn" title="Mute">🔊</button>
                <select id="rate" title="Speed">
                    <option value="0.5">0.5×</option>
                    <option value="1" selected>1×</option>
                    <option value="1.25">1.25×</option>
                    <option value="1.5">1.5×</option>
                    <option value="2">2×</option>
                </select>
                <button id="fsBtn" title="Fullscreen">⛶</button>
            </div>`;
    }

    function wireControls() {
        const playBtn = document.getElementById("playBtn");
        const centerBtn = document.getElementById("centerBtn");
        const muteBtn = document.getElementById("muteBtn");
        const seek = document.getElementById("seek");
        const cur = document.getElementById("cur");
        const dur = document.getElementById("dur");
        const rate = document.getElementById("rate");
        const fsBtn = document.getElementById("fsBtn");
        const shield = document.getElementById("shield");
        let seeking = false;

        function isPlaying() {
            return player && player.getPlayerState && player.getPlayerState() === window.YT.PlayerState.PLAYING;
        }
        function toggle() {
            if (!player) return;
            isPlaying() ? player.pauseVideo() : player.playVideo();
        }
        playBtn.onclick = toggle;
        centerBtn.onclick = toggle;
        shield.onclick = toggle;           // clicking the video toggles play, never reaches YouTube
        shield.ondblclick = () => fsBtn.click();

        muteBtn.onclick = () => {
            if (!player) return;
            if (player.isMuted()) { player.unMute(); muteBtn.textContent = "🔊"; }
            else { player.mute(); muteBtn.textContent = "🔇"; }
        };
        rate.onchange = () => player && player.setPlaybackRate(parseFloat(rate.value));
        fsBtn.onclick = () => {
            if (document.fullscreenElement) document.exitFullscreen();
            else root.requestFullscreen && root.requestFullscreen();
        };
        seek.addEventListener("input", () => { seeking = true; });
        seek.addEventListener("change", () => {
            if (player) player.seekTo((seek.value / 100) * player.getDuration(), true);
            seeking = false;
        });

        return { playBtn, centerBtn, cur, dur, seek, get seeking() { return seeking; } };
    }

    function startProgress(ui) {
        clearInterval(progressTimer);
        let tick = 0;
        progressTimer = setInterval(() => {
            if (!player || !player.getDuration) return;
            const d = player.getDuration();
            const t = player.getCurrentTime();
            ui.dur.textContent = fmt(d);
            ui.cur.textContent = fmt(t);
            if (!ui.seeking && d > 0) ui.seek.value = (t / d) * 100;

            // Report progress roughly every 10s of playback, and latch
            // completion once ~90% (or the last 15s) has been watched.
            const playing = player.getPlayerState &&
                player.getPlayerState() === window.YT.PlayerState.PLAYING;
            if (playing && d > 0) {
                const nearEnd = t / d >= 0.9 || d - t <= 15;
                if (nearEnd && !completed) {
                    saveProgress(t, true);
                } else if (++tick % 40 === 0) {  // 40 × 250ms ≈ 10s
                    saveProgress(t, false);
                }
            }
        }, 250);
    }

    function reflectState(state, ui) {
        const playing = state === window.YT.PlayerState.PLAYING;
        ui.playBtn.textContent = playing ? "❚❚" : "▶";
        ui.centerBtn.style.display = playing ? "none" : "flex";
        root.classList.toggle("paused", !playing);
    }

    async function init() {
        buildShell();
        const ui = wireControls();
        try {
            const [, data] = await Promise.all([loadApi(), fetchSource()]);
            const meta = data;
            player = new window.YT.Player("yt-frame", {
                videoId: meta.videoId,
                playerVars: {
                    controls: 0, modestbranding: 1, rel: 0, fs: 0,
                    disablekb: 1, iv_load_policy: 3, playsinline: 1, showinfo: 0,
                    origin: window.location.origin,
                },
                events: {
                    onReady: () => startProgress(ui),
                    onStateChange: (e) => {
                        reflectState(e.data, ui);
                        // Seek to the saved resume point the first time playback
                        // starts (skip if already near the end / completed).
                        if (e.data === window.YT.PlayerState.PLAYING && !resumed) {
                            resumed = true;
                            const d = player.getDuration();
                            if (resumeAt > 3 && (!d || resumeAt < d - 15)) {
                                player.seekTo(resumeAt, true);
                            }
                        }
                        if (e.data === window.YT.PlayerState.PAUSED) {
                            saveProgress(player.getCurrentTime(), false);
                        }
                        if (e.data === window.YT.PlayerState.ENDED) {
                            saveProgress(player.getCurrentTime(), true);
                        }
                    },
                },
            });
        } catch (err) {
            root.innerHTML = '<div class="loading">This video is unavailable.</div>';
        }
    }

    // Best-effort save when the student navigates away mid-video.
    window.addEventListener("pagehide", () => {
        if (!progressUrl || !player || !player.getCurrentTime) return;
        const t = Math.floor(player.getCurrentTime() || 0);
        if (t <= 0 || Math.abs(t - lastSavedPos) < 5) return;
        const body = new URLSearchParams({
            position: String(t),
            csrfmiddlewaretoken: csrf || "",
        });
        // sendBeacon survives the page unload where fetch would be cancelled.
        if (navigator.sendBeacon) navigator.sendBeacon(progressUrl, body);
    });

    init();
})();
