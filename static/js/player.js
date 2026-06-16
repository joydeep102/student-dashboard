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
    let player = null;
    let progressTimer = null;

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
        progressTimer = setInterval(() => {
            if (!player || !player.getDuration) return;
            const d = player.getDuration();
            const t = player.getCurrentTime();
            ui.dur.textContent = fmt(d);
            ui.cur.textContent = fmt(t);
            if (!ui.seeking && d > 0) ui.seek.value = (t / d) * 100;
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
                    onStateChange: (e) => reflectState(e.data, ui),
                },
            });
        } catch (err) {
            root.innerHTML = '<div class="loading">This video is unavailable.</div>';
        }
    }

    init();
})();
