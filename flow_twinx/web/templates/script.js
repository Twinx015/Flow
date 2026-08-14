const audio = document.getElementById("audioPlayer");
const playBtn = document.getElementById("playBtn");
const miniPlayBtn = document.getElementById("miniPlayBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const shuffleBtn = document.getElementById("shuffleBtn");
const repeatBtn = document.getElementById("repeatBtn");
const progressFill = document.getElementById("progressFill");
const progressBar = document.getElementById("progressBar");
const currentTime = document.getElementById("currentTime");
const totalTime = document.getElementById("totalTime");
const volumeSlider = document.getElementById("volumeSlider");
const albumArt = document.getElementById("albumArt");
const trackTitle = document.getElementById("trackTitle");
const trackArtist = document.getElementById("trackArtist");
const playerBg = document.getElementById("playerBg");
const miniArt = document.getElementById("miniArt");
const miniTitle = document.getElementById("miniTitle");
const miniArtist = document.getElementById("miniArtist");
const miniPlayer = document.getElementById("miniPlayer");
const playerMain = document.getElementById("playerMain");
const miniExpandBtn = document.getElementById("miniExpandBtn");
const settingsModal = document.getElementById("settingsModal");
const settingsBtn = document.getElementById("settingsBtn");
const closeSettings = document.getElementById("closeSettings");
const saveSettings = document.getElementById("saveSettings");
const resetSettingsBtn = document.getElementById("resetSettings");
const searchInput = document.getElementById("searchInput");
const resultsContainer = document.getElementById("resultsContainer");
const srcYt = document.getElementById("srcYt");
const srcLocal = document.getElementById("srcLocal");
const clearQueueBtn = document.getElementById("clearQueueBtn");
const queueContainer = document.getElementById("queueContainer");
const scanLocalBtn = document.getElementById("scanLocalBtn");
const localShuffleBtn = document.getElementById("localShuffleBtn");
const albumsGrid = document.getElementById("albumsGrid");
const albumSongs = document.getElementById("albumSongs");
const localSongsContainer = document.getElementById("localSongs");
const queueBar = document.getElementById("queueBar");
const queueBarTitle = document.getElementById("queueBarTitle");
const queueBarCount = document.getElementById("queueBarCount");
const queueBarArt = document.getElementById("queueBarArt");
const queueBarExpand = document.getElementById("queueBarExpand");
const queueOverlay = document.getElementById("queueOverlay");
const queueOverlayClose = document.getElementById("queueOverlayClose");
const autoPlayToggle = document.getElementById("autoPlayToggle");
const downloadBtn = document.getElementById("downloadBtn");
const toastEl = document.getElementById("toast");
const setDownloadPath = document.getElementById("setDownloadPath");
const refreshLikedBtn = document.getElementById("refreshLikedBtn");
const likeBtn = document.getElementById("likeBtn");
const newPlaylistBtn = document.getElementById("newPlaylistBtn");
const refreshPlaylistsBtn = document.getElementById("refreshPlaylistsBtn");
const playlistsGrid = document.getElementById("playlistsGrid");
const playlistSongs = document.getElementById("playlistSongs");
const playlistModal = document.getElementById("playlistModal");
const closePlaylistModal = document.getElementById("closePlaylistModal");
const playlistModalTitle = document.getElementById("playlistModalTitle");
const playlistNameInput = document.getElementById("playlistNameInput");
const savePlaylistBtn = document.getElementById("savePlaylistBtn");
const playlistExistsModal = document.getElementById("playlistExistsModal");
const closeExistsModal = document.getElementById("closeExistsModal");
const existsMsg = document.getElementById("existsMsg");
const existsAppendBtn = document.getElementById("existsAppendBtn");
const existsOverwriteBtn = document.getElementById("existsOverwriteBtn");

let queue = [];
let queueIndex = -1;
let playHistory = [];
let nowPlayingTrack = null;
let isPlaying = false;
let isShuffled = false;
let repeatMode = 0; // 0=off, 1=repeat-one, 2=repeat-all
let autoPlay = true;
let searchSource = "youtube";
let activeTab = "search";
let localTracks = [];
let currentTrackType = null;
let downloadedIds = new Set();
let librarySongs = {};
let currentDownloaded = false;
let playlistsCache = [];
let currentPlaylistName = null;
let pendingPlaylist = null;
let pendingSong = null;
let playlistModalMode = "saveQueue";

let settings = {
  theme: "dark",
  accent: "#6c63ff",
  bgBlur: 10,
  bgDim: 60,
  defaultVolume: 80,
  crossfade: 0,
  miniOnBlur: false,
  defaultSource: "youtube",
  format: "webm",
};

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

let searchTimer = null;

function debounceSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => doSearch(), 1000);
}

searchInput.addEventListener("input", debounceSearch);

searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    clearTimeout(searchTimer);
    doSearch();
  }
});

function doSearch() {
  const q = searchInput.value.trim();
  if (q.length < 2) {
    resultsContainer.innerHTML = "";
    return;
  }
  if (searchSource === "youtube") {
    searchYouTube(q);
  } else {
    searchLocal(q);
  }
}

srcYt.addEventListener("click", () => setSearchSource("youtube"));
srcLocal.addEventListener("click", () => setSearchSource("local"));

function setSearchSource(source) {
  searchSource = source;
  srcYt.classList.toggle("active", source === "youtube");
  srcLocal.classList.toggle("active", source === "local");
  doSearch();
}

playBtn.addEventListener("click", togglePlay);
miniPlayBtn.addEventListener("click", togglePlay);
prevBtn.addEventListener("click", prevTrack);
nextBtn.addEventListener("click", nextTrack);
shuffleBtn.addEventListener("click", toggleShuffle);
localShuffleBtn.addEventListener("click", localShufflePlay);
repeatBtn.addEventListener("click", toggleRepeat);
volumeSlider.addEventListener("input", (e) => {
  audio.volume = e.target.value / 100;
});
audio.addEventListener("timeupdate", updateProgress);
audio.addEventListener("loadedmetadata", () => {
  updateTotalTime();
  if (nowPlayingTrack) {
    reportNowPlaying(nowPlayingTrack, !audio.paused);
  }
});
audio.addEventListener("ended", handleEnd);
audio.addEventListener("play", () => {
  updatePlayBtn(true);
  reportNowPlaying(queue[queueIndex], true);
});
audio.addEventListener("pause", () => {
  updatePlayBtn(false);
  reportNowPlaying(queue[queueIndex], false);
});
audio.addEventListener("error", () => {
  console.error("Playback error, trying next");
  nextTrack();
});

progressBar.addEventListener("click", (e) => {
  const rect = progressBar.getBoundingClientRect();
  const pct = (e.clientX - rect.left) / rect.width;
  audio.currentTime = pct * audio.duration;
});

clearQueueBtn.addEventListener("click", clearQueue);
document.getElementById("saveQueueBtn").addEventListener("click", openSavePlaylistModal);
scanLocalBtn.addEventListener("click", scanLocal);
refreshLikedBtn.addEventListener("click", loadLiked);
newPlaylistBtn.addEventListener("click", openNewPlaylistModal);
refreshPlaylistsBtn.addEventListener("click", loadPlaylists);

miniExpandBtn.addEventListener("click", () => {
  miniPlayer.style.display = "none";
  playerMain.style.display = "flex";
  document.querySelector(".sidebar").style.width = "";
  document.querySelector(".sidebar").style.minWidth = "";
  document.querySelector(".sidebar").style.display = "";
});

settingsBtn.addEventListener("click", () =>
  settingsModal.classList.add("open"),
);
closeSettings.addEventListener("click", () =>
  settingsModal.classList.remove("open"),
);
settingsModal.addEventListener("click", (e) => {
  if (e.target === settingsModal) settingsModal.classList.remove("open");
});
saveSettings.addEventListener("click", saveSettingsToAPI);
resetSettingsBtn.addEventListener("click", resetSettings);

playlistModal.addEventListener("click", (e) => {
  if (e.target === playlistModal) playlistModal.classList.remove("open");
});
closePlaylistModal.addEventListener("click", () =>
  playlistModal.classList.remove("open"),
);
playlistNameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitPlaylistModal();
});
savePlaylistBtn.addEventListener("click", submitPlaylistModal);
playlistExistsModal.addEventListener("click", (e) => {
  if (e.target === playlistExistsModal) playlistExistsModal.classList.remove("open");
});
closeExistsModal.addEventListener("click", () =>
  playlistExistsModal.classList.remove("open"),
);
existsAppendBtn.addEventListener("click", () => {
  if (pendingPlaylist) {
    doSavePlaylist(pendingPlaylist.name, pendingPlaylist.songs, "append");
  }
  playlistExistsModal.classList.remove("open");
});
existsOverwriteBtn.addEventListener("click", () => {
  if (pendingPlaylist) {
    doSavePlaylist(pendingPlaylist.name, pendingPlaylist.songs, "overwrite");
  }
  playlistExistsModal.classList.remove("open");
});

autoPlayToggle.addEventListener("change", (e) => {
  autoPlay = e.target.checked;
  if (!autoPlay) {
    if (queueIndex >= 0 && queue[queueIndex]) {
      const currentTrack = queue[queueIndex];
      queue = queue.filter((song, idx) => idx === queueIndex || !song._autoAdded);
      queueIndex = queue.indexOf(currentTrack);
    } else {
      queue = queue.filter((song) => !song._autoAdded);
      if (queueIndex >= queue.length) queueIndex = queue.length - 1;
    }
    renderQueue();
  }
});

queueBar.addEventListener("click", (e) => {
  if (
    e.target.closest(".autoplay-toggle") ||
    e.target.closest("#queueBarExpand")
  )
    return;
  toggleQueueOverlay();
});

queueBarExpand.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleQueueOverlay();
});

queueOverlayClose.addEventListener("click", () => {
  queueOverlay.classList.remove("open");
  queueBarExpand.classList.remove("open");
});

function toggleQueueOverlay() {
  const isOpen = queueOverlay.classList.toggle("open");
  queueBarExpand.classList.toggle("open", isOpen);
}

function setTab(tab) {
  activeTab = tab;
  document
    .querySelectorAll(".sidebar-tabs .tab")
    .forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  const tabId = "tab" + tab.charAt(0).toUpperCase() + tab.slice(1);
  document.querySelectorAll(".sidebar-content .tab-content").forEach((t) => {
    t.classList.toggle("active", t.id === tabId);
  });
}

document.querySelectorAll(".sidebar-tabs .tab").forEach((tab) => {
  if (tab.dataset.tab) {
    tab.addEventListener("click", () => setTab(tab.dataset.tab));
  }
});

document.addEventListener("visibilitychange", () => {
  if (
    settings.miniOnBlur &&
    document.hidden &&
    playerMain.style.display !== "none"
  ) {
    goMini();
  }
});


function togglePlay() {
  if (audio.paused) {
    if (audio.src && audio.src !== "") {
      audio.play();
    } else if (queue.length > 0 && queueIndex >= 0) {
      loadAndPlay(queue[queueIndex]);
    } else if (queue.length > 0) {
      queueIndex = 0;
      loadAndPlay(queue[0]);
    }
  } else {
    audio.pause();
  }
}

function updatePlayBtn(playing) {
  isPlaying = playing;
  const icon = playing ? "bi bi-pause-fill" : "bi bi-play-fill";
  playBtn.querySelector("i").className = icon;
  miniPlayBtn.querySelector("i").className = icon;
  document.body.classList.toggle("playing", playing);
}

function reportNowPlaying(track, playing) {
  if (!track) return;
  let dur = track.duration || 0;
  if (isFinite(audio.duration) && audio.duration > 0) {
    dur = Math.round(audio.duration);
  }
  fetch("/api/now-playing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: track.title || "Unknown",
      duration: dur,
      playing: playing,
    }),
  }).catch(() => {});
}

function loadAndPlay(track) {
  if (!track) return;
  nowPlayingTrack = track;
  currentTrackType = track.source || "yt";
  setDisplayInfo(track);
  updateActiveCard(track);
  updateMiniPlayer(track);
  updateBg(effectiveThumb(track));
  updateQueueBar();
  checkLiked(track.video_id);
  checkDownload(track.video_id);
  reportNowPlaying(track, true);
  setTimeout(() => reportNowPlaying(nowPlayingTrack, !audio.paused), 800);

  if (currentTrackType === "local") {
    let filePath = track.path || track.url || "";
    let encodedPath = encodeURI(filePath);
    let src = "/local" + (encodedPath.startsWith("/") ? encodedPath : "/" + encodedPath);
    track.thumbnail = track.thumbnail || "";
    track.channel = track.channel || track.album || "Local Music";
    audio.src = src;
    audio.play().catch(() => {});
  } else if (track.stream_url) {
    audio.src = track.stream_url;
    audio.play().catch(() => {});
  } else if (track.video_id) {
    fetch(`/play?video_id=${track.video_id}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.stream_url) {
          track.stream_url = data.stream_url;
          audio.src = data.stream_url;
          audio.play().catch(() => {});
        }
      });
  }

  if (autoPlay && currentTrackType !== "local" && track.video_id) {
    autoLoadRecommendations(track.video_id);
  }
}

const artFrame = "/static/Frame%201.jpg";

function effectiveThumb(track) {
  const id = track && track.video_id;
  if (id && librarySongs[id] && librarySongs[id].thumbnail) {
    return "/thumb/" + id;
  }
  return track ? track.thumbnail || "" : "";
}

function applyArt(img, url, track) {
  url = track ? effectiveThumb(track) : url;
  if (!url || !url.trim()) {
    img.onerror = null;
    img.src = artFrame;
    return;
  }
  img.onerror = () => {
    const cur = img.src;
    img.onerror = null;
    if (cur.includes("maxresdefault.jpg")) {
      img.src = cur.replace("maxresdefault.jpg", "hqdefault.jpg");
    } else {
      img.src = artFrame;
    }
  };
  img.src = url;
}

function artImgTag(url, track) {
  url = track ? effectiveThumb(track) : url;
  if (!url || !url.trim()) {
    return `<img src="${artFrame}" alt="" loading="lazy">`;
  }
  const onerr =
    "this.onerror=null;if(this.src.includes('maxresdefault.jpg')){this.src=this.src.replace('maxresdefault.jpg','hqdefault.jpg')}else{this.src='/static/Frame%201.jpg'}";
  return `<img src="${url}" onerror="${onerr}" alt="" loading="lazy">`;
}

function setDisplayInfo(track) {
  trackTitle.textContent = track.title || "Unknown";
  trackArtist.textContent = track.channel || track.artist || "";
  applyArt(albumArt, track.thumbnail, track);
}

function updateMiniPlayer(track) {
  applyArt(miniArt, track.thumbnail, track);
  miniTitle.textContent = track.title || "Unknown";
  miniArtist.textContent = track.channel || track.artist || "";
}

function updateBg(url) {
  if (url && url.trim() !== "") {
    playerBg.style.backgroundImage = `url(${url})`;
  } else {
    playerBg.style.backgroundImage = "none";
  }
}

function updateActiveCard(track) {
  document
    .querySelectorAll(".song-card")
    .forEach((c) => c.classList.remove("active"));
  const cards = document.querySelectorAll(".song-card");
  cards.forEach((c) => {
    const t = c.dataset.title;
    const id = c.dataset.videoId || c.dataset.path;
    if (t === track.title && id === (track.video_id || track.path)) {
      c.classList.add("active");
    }
  });
}

function updateProgress() {
  if (!audio.duration) return;
  const pct = (audio.currentTime / audio.duration) * 100;
  progressFill.style.width = pct + "%";
  currentTime.textContent = formatTime(audio.currentTime);
}

function updateTotalTime() {
  totalTime.textContent = formatTime(audio.duration);
}

function formatTime(s) {
  if (isNaN(s) || !isFinite(s)) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

let lastRecommendationId = null;
let recommendationLoading = false;

function autoLoadRecommendations(videoId) {
  if (!videoId || recommendationLoading) return;
  const songsRemaining = queue.length - queueIndex - 1;
  if (songsRemaining >= 5) return;
  if (videoId === lastRecommendationId) return;
  lastRecommendationId = videoId;
  recommendationLoading = true;
  fetch(`/recommend?video_id=${encodeURIComponent(videoId)}&limit=20`)
    .then((r) => r.json())
    .then((data) => {
      const results = data.results || [];
      const existingIds = new Set(queue.map((t) => t.video_id));
      let added = 0;
      results.forEach((item) => {
        if (!item.video_id || existingIds.has(item.video_id)) return;
        queue.push({ ...item, source: "yt", _autoAdded: true });
        existingIds.add(item.video_id);
        added++;
      });
      if (added > 0) renderQueue();
      recommendationLoading = false;
    })
    .catch(() => {
      recommendationLoading = false;
    });
}

function handleEnd() {
  if (repeatMode === 1) {
    audio.play();
    return;
  }
  if (!autoPlay && repeatMode !== 2) {
    updatePlayBtn(false);
    audio.currentTime = 0;
    return;
  }
  if (queueIndex < queue.length - 1 || repeatMode === 2) {
    nextTrack();
  } else {
    updatePlayBtn(false);
    audio.currentTime = 0;
  }
}

function prevTrack() {
  if (audio.currentTime > 3) {
    audio.currentTime = 0;
    return;
  }
  if (playHistory.length > 0) {
    const prev = playHistory.pop();
    if (prev) {
      loadAndPlay(prev);
      return;
    }
  }
  if (queueIndex > 0) {
    queueIndex--;
    loadAndPlay(queue[queueIndex]);
  }
}

function nextTrack() {
  const prev = queue[queueIndex];
  if (isShuffled && queue.length > 0) {
    let nextIdx;
    do {
      nextIdx = Math.floor(Math.random() * queue.length);
    } while (nextIdx === queueIndex && queue.length > 1);
    queueIndex = nextIdx;
  } else {
    if (queueIndex < queue.length - 1) {
      queueIndex++;
    } else if (repeatMode === 2) {
      queueIndex = 0;
    } else {
      return;
    }
  }
  if (prev) {
    playHistory.push(prev);
    if (playHistory.length > 50) playHistory.shift();
  }
  loadAndPlay(queue[queueIndex]);
}

function toggleShuffle() {
  isShuffled = !isShuffled;
  shuffleBtn.classList.toggle("active", isShuffled);
  if (localShuffleBtn) localShuffleBtn.classList.toggle("active", isShuffled);
}

function localShufflePlay() {
  if (localTracks.length === 0) {
    showToast("No local music to shuffle");
    return;
  }
  if (!isShuffled) toggleShuffle();
  const randomIdx = Math.floor(Math.random() * localTracks.length);
  playLocal(localTracks[randomIdx], localTracks);
}

function toggleRepeat() {
  repeatMode = (repeatMode + 1) % 3;
  const icons = ["bi bi-repeat", "bi bi-repeat-1", "bi bi-repeat"];
  const titles = ["Repeat off", "Repeat one", "Repeat all"];
  repeatBtn.querySelector("i").className = icons[repeatMode];
  repeatBtn.title = titles[repeatMode];
  if (repeatMode === 0) repeatBtn.classList.remove("active");
  else repeatBtn.classList.add("active");
}

function clearQueue() {
  queue = [];
  queueIndex = -1;
  audio.pause();
  audio.src = "";
  updatePlayBtn(false);
  renderQueue();
  queueOverlay.classList.remove("open");
  queueBarExpand.classList.remove("open");
  queueBarExpand.querySelector("i").className = "bi bi-list-ul";
}


function searchYouTube(query) {
  const limit = 15;
  fetch(`/search?q=${encodeURIComponent(query)}&limit=${limit}`)
    .then((r) => r.json())
    .then((data) => {
      const res = data.results || [];
      resultsContainer.innerHTML = "";
      res.forEach((item) => {
        const card = createSongCard(item, "yt");
        card.addEventListener("click", () => playTrack(item));
        const addBtn = card.querySelector(".song-actions button");
        addBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          addToQueue(item);
        });
        resultsContainer.appendChild(card);
      });
      // markDownloadedCards();
    })
    .catch(() => {});
}

function searchLocal(query) {
  fetch(`/api/local-search?q=${encodeURIComponent(query)}`)
    .then((r) => r.json())
    .then((data) => {
      const res = data.results || [];
      resultsContainer.innerHTML = "";
      if (res.length === 0) {
        resultsContainer.innerHTML =
          '<div style="color: var(--text3); text-align:center; padding:20px; font-size: 13px;">No local results</div>';
        return;
      }
      res.forEach((item) => {
        const card = createSongCard(
          { ...item, thumbnail: "", channel: "Local Music", duration: 0 },
          "local",
        );
        card.addEventListener("click", () => playLocal(item, [item]));
        const addBtn = card.querySelector(".song-actions button");
        addBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          addToQueue({ ...item, source: "local" });
        });
        resultsContainer.appendChild(card);
      });
      // markDownloadedCards();
    })
    .catch(() => {});
}

function createSongCard(data, type) {
  const card = document.createElement("div");
  card.className = "song-card";
  card.dataset.title = data.title;
  card.dataset.videoId = data.video_id || "";
  card.dataset.path = data.path || "";
  const downloaded =
    data.video_id && downloadedIds.has(data.video_id);
  card.innerHTML = `
    ${artImgTag(data.thumbnail, data)}
    <div class="song-info">
      <div class="song-title">${data.title || "Unknown"}</div>
      <div class="song-artist">${data.channel || data.artist || "Unknown"}</div>
    </div>
    ${data.duration ? `<span class="song-duration">${formatTime(data.duration)}</span>` : ""}
    <div class="song-actions">
      <button title="Add to queue"><i class="bi bi-plus-lg"></i></button>
      <button class="pl-add-btn" title="Add to playlist"><i class="bi bi-music-note-list"></i></button>
    </div>
  `;
  const plBtn = card.querySelector(".pl-add-btn");
  plBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    openPlaylistMenu(plBtn, data);
  });
  return card;
}

function playTrack(item, list) {
  const src = list && list.length ? list : [item];
  const tracks = src.map((t) => ({ ...t, source: "yt" }));
  addHistory();
  queue = tracks;
  queueIndex = Math.max(0, queue.findIndex((e) => e.video_id === item.video_id));
  loadAndPlay(queue[queueIndex]);
  renderQueue();
}

function playLocal(item, list) {
  const src = list && list.length ? list : localTracks.length ? localTracks : [item];
  const tracks = src.map((t) => ({
    ...t,
    source: "local",
    channel: t.channel || t.album || "Local Music",
  }));
  addHistory();
  queue = tracks;
  queueIndex = Math.max(0, queue.findIndex((e) => e.path === item.path));
  loadAndPlay(queue[queueIndex]);
  renderQueue();
}

function addHistory() {
  if (queueIndex >= 0 && queue[queueIndex]) {
    playHistory.push(queue[queueIndex]);
    if (playHistory.length > 50) playHistory.shift();
  }
}

function loadIndex(arr, item) {
  return arr.findIndex(
    (a) => a.video_id === item.video_id || a.path === item.path,
  );
}

function addToQueue(item, doRender = true) {
  if (item.source === "local") {
    item.channel = item.channel || "Local Music";
  }
  queue.push(item);
  if (queueIndex === -1) {
    queueIndex = 0;
  }
  if (doRender) renderQueue();
}

function renderQueue() {
  queueContainer.innerHTML =
    queue.length === 0
      ? '<div style="color: var(--text3);text-align:center;padding:20px;font-size:13px;">Queue is empty</div>'
      : "";
  queue.forEach((item, idx) => {
    const card = document.createElement("div");
    card.className =
      "song-card" +
      (idx === queueIndex && item === queue[queueIndex] ? " active" : "");
    card.dataset.title = item.title;
    card.dataset.videoId = item.video_id || "";
    card.dataset.path = item.path || "";
    const dur = item.duration || "";
    const downloaded =
      item.video_id && downloadedIds.has(item.video_id);
    card.innerHTML = `
      ${artImgTag(item.thumbnail, item)}
      <div class="song-info">
        <div class="song-title">${item.title}</div>
        <div class="song-artist">${item.channel || item.artist || "Unknown"}</div>
      </div>
      ${dur ? `<span class="song-duration">${formatTime(dur)}</span>` : ""}
      <div class="song-actions">
        <button class="queue-remove" data-idx="${idx}" title="Remove"><i class="bi bi-x-lg"></i></button>
        <button class="pl-add-btn" title="Add to playlist"><i class="bi bi-music-note-list"></i></button>
      </div>
    `;
    card.addEventListener("click", () => {
      addHistory();
      queueIndex = idx;
      loadAndPlay(item);
      renderQueue();
    });
    card.querySelector(".queue-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      removeFromQueue(parseInt(e.currentTarget.dataset.idx));
    });
    card.querySelector(".pl-add-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      openPlaylistMenu(e.currentTarget, item);
    });
    queueContainer.appendChild(card);
  });
  updateQueueBar();
}

function updateQueueBar() {
  const nextIdx = queueIndex + 1;
  if (queue.length > 0 && nextIdx < queue.length) {
    const nextTrack = queue[nextIdx];
    queueBarTitle.textContent = nextTrack.title || "Unknown";
    applyArt(queueBarArt, nextTrack.thumbnail, nextTrack);
  } else if (queue.length > 0) {
    queueBarTitle.textContent = "End of queue";
    applyArt(queueBarArt, "");
  } else {
    queueBarTitle.textContent = "Queue empty";
    applyArt(queueBarArt, "");
  }
  updateQueueBarInfo();
}

function updateQueueBarInfo() {
  const nextIdx = queueIndex + 1;
  if (queue.length > 0) {
    const remaining = queue.length - nextIdx;
    queueBarCount.textContent =
      remaining > 0
        ? `${queue.length} songs \u00b7 ${remaining} next`
        : `${queue.length} song${queue.length !== 1 ? "s" : ""}`;
  } else {
    queueBarCount.textContent = "";
  }
}

function removeFromQueue(idx) {
  const wasPlaying = idx === queueIndex;
  queue.splice(idx, 1);
  if (wasPlaying) {
    if (queue.length === 0) {
      queueIndex = -1;
      audio.pause();
      audio.src = "";
      updatePlayBtn(false);
    } else {
      queueIndex = idx >= queue.length ? queue.length - 1 : idx;
      loadAndPlay(queue[queueIndex]);
    }
  } else if (idx < queueIndex) {
    queueIndex--;
  }
  renderQueue();
}


function scanLocal() {
  fetch("/offline")
    .then((r) => r.json())
    .then((data) => {
      localTracks = (data.results || []).map((t) => ({
        ...t,
        source: "local",
        channel: "Local Files",
      }));
      loadLocalTracks();
    })
    .catch(() => {});
  fetch("/api/albums")
    .then((r) => r.json())
    .then((data) => {
      albumsGrid.innerHTML = "";
      (data.albums || []).forEach((album) => {
        const card = document.createElement("div");
        card.className = "album-card";
        card.innerHTML = `<i class="bi bi-folder2-open"></i><span>${album}</span>`;
        card.addEventListener("click", () => showAlbumSongs(album));
        albumsGrid.appendChild(card);
      });
    })
    .catch(() => {});
}

function showAlbumSongs(album) {
  fetch(`/api/album/${encodeURIComponent(album)}`)
    .then((r) => r.json())
    .then((data) => {
      const songs = data.results || [];
      albumSongs.innerHTML = `<div class="album-header"><button id="albumBackBtn"><i class="bi bi-arrow-left"></i></button> ${album}</div>`;
      document.getElementById("albumBackBtn").addEventListener("click", () => {
        albumSongs.innerHTML = "";
      });
      songs.forEach((item) => {
        const entry = {
          title: item.title,
          path: item.path,
          source: "local",
          channel: album,
          thumbnail: "",
        };
        const card = createSongCard(entry, "local");
        card.addEventListener("click", () => playLocal(entry, songs));
        const addBtn = card.querySelector(".song-actions button");
        addBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          addToQueue(entry);
        });
        albumSongs.appendChild(card);
      });
    })
    .catch(() => {});
}

function loadLocalTracks() {
  if (localTracks.length === 0) {
    localSongsContainer.innerHTML =
      '<div style="color: var(--text3); text-align:center; padding: 20px; font-size: 13px;">No local music. <strong>Scan</strong> to load.</div>';
    return;
  }
  localSongsContainer.innerHTML = "";
  localTracks.forEach((t) => {
    const card = createSongCard(t, "local");
    card.addEventListener("click", () => playLocal(t, localTracks));
    const addBtn = card.querySelector(".song-actions button");
    addBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      addToQueue(t);
    });
    localSongsContainer.appendChild(card);
  });
}

function toPlaylistSong(track) {
  const song = { title: (track.title || "Unknown").trim() };
  if (track.video_id) {
    song.video_id = track.video_id;
    song.url = `https://www.youtube.com/watch?v=${track.video_id}`;
  } else if (track.path) {
    song.url = track.path;
  }
  return song;
}

function openSavePlaylistModal() {
  const songs = queue.filter((t) => !t._autoAdded);
  if (songs.length === 0) {
    showToast("Queue is empty");
    return;
  }
  playlistModalMode = "saveQueue";
  playlistModalTitle.innerHTML =
    '<i class="bi bi-music-note-list"></i> Save as Playlist';
  playlistNameInput.value = "";
  playlistModal.classList.add("open");
  setTimeout(() => playlistNameInput.focus(), 50);
}

function openNewPlaylistModal() {
  playlistModalMode = "create";
  playlistModalTitle.innerHTML =
    '<i class="bi bi-plus-lg"></i> New Playlist';
  playlistNameInput.value = "";
  playlistModal.classList.add("open");
  setTimeout(() => playlistNameInput.focus(), 50);
}

function submitPlaylistModal() {
  const name = playlistNameInput.value.trim();
  if (!name) {
    showToast("Enter a playlist name");
    return;
  }
  if (playlistModalMode === "create") {
    createPlaylist(name).then((ok) => {
      if (ok) playlistModal.classList.remove("open");
    });
    return;
  }
  if (playlistModalMode === "song") {
    if (pendingSong) addSongToPlaylist(name, pendingSong);
    playlistModal.classList.remove("open");
    pendingSong = null;
    return;
  }
  const songs = queue.filter((t) => !t._autoAdded).map(toPlaylistSong);
  if (songs.length === 0) {
    showToast("No playable tracks in queue");
    return;
  }
  pendingPlaylist = { name, songs };
  fetch("/api/playlists")
    .then((r) => r.json())
    .then((data) => {
      const exists = (data.playlists || []).some((p) => p.name === name);
      if (exists) {
        openExistsDialog(name, songs);
        playlistModal.classList.remove("open");
      } else {
        doSavePlaylist(name, songs, "append");
      }
    });
}

function doSavePlaylist(name, songs, mode) {
  fetch("/api/playlists/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, songs, mode }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        playlistModal.classList.remove("open");
        showToast(`Saved ${data.count} song${data.count !== 1 ? "s" : ""} to "${name}"`);
        loadPlaylists();
      } else {
        showToast("Failed: " + (data.error || "Unknown error"));
      }
    })
    .catch(() => showToast("Save failed"));
}

function openExistsDialog(name, songs) {
  pendingPlaylist = { name, songs };
  existsMsg.textContent = `Playlist "${name}" already exists. Append or overwrite?`;
  playlistExistsModal.classList.add("open");
}

function loadPlaylists() {
  fetch("/api/playlists")
    .then((r) => r.json())
    .then((data) => {
      playlistsCache = data.playlists || [];
      renderPlaylists();
    })
    .catch(() => {});
}

function renderPlaylists() {
  playlistsGrid.innerHTML = playlistsCache.length
    ? ""
    : '<div style="color:var(--text3);font-size:13px;grid-column:1/-1;">No playlists yet</div>';
  playlistsCache.forEach((p) => {
    const card = document.createElement("div");
    card.className = "album-card playlist-card";
    card.innerHTML = `<i class="bi bi-music-note-list"></i><span>${p.name}</span><small>${p.count} song${p.count !== 1 ? "s" : ""}</small>`;
    card.addEventListener("click", () => openPlaylist(p.name));
    playlistsGrid.appendChild(card);
  });
}

function openPlaylist(name) {
  currentPlaylistName = name;
  fetch(`/api/playlist?name=${encodeURIComponent(name)}`)
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        showToast(data.error);
        return;
      }
      renderPlaylistDetail(data.name, data.songs || []);
    })
    .catch(() => {});
}

function renderPlaylistDetail(name, songs) {
  playlistSongs.innerHTML = `<div class="album-header">
    <button id="plBackBtn" title="Back"><i class="bi bi-arrow-left"></i></button>
    <span>${name}</span>
    <button id="plPlayBtn" title="Play"><i class="bi bi-play-fill"></i></button>
    <button id="plDeleteBtn" title="Delete playlist"><i class="bi bi-trash"></i></button>
  </div>`;
  document.getElementById("plBackBtn").addEventListener("click", () => {
    playlistSongs.innerHTML = "";
  });
  document.getElementById("plPlayBtn").addEventListener("click", () =>
    playPlaylist(songs),
  );
  document.getElementById("plDeleteBtn").addEventListener("click", () =>
    deletePlaylist(name),
  );
  if (songs.length === 0) {
    playlistSongs.insertAdjacentHTML(
      "beforeend",
      '<div style="color:var(--text3);text-align:center;padding:20px;font-size:13px;">Playlist is empty</div>',
    );
    return;
  }
  songs.forEach((item, idx) => {
    const entry = {
      ...item,
      source: item.video_id ? "yt" : "local",
      channel: item.channel || "Playlist",
      duration: item.duration || 0,
    };
    const card = createSongCard(entry, entry.source);
    card.addEventListener("click", () => playPlaylist(songs, idx));
    const removeBtn = document.createElement("button");
    removeBtn.className = "pl-remove";
    removeBtn.title = "Remove from playlist";
    removeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      removeFromPlaylist(name, idx);
    });
    card.querySelector(".song-actions").appendChild(removeBtn);
    playlistSongs.appendChild(card);
  });
}

function playPlaylist(songs, startIdx) {
  if (!songs.length) return;
  startIdx = startIdx || 0;
  const entries = songs.map((s) => ({
    ...s,
    source: s.video_id ? "yt" : "local",
    channel: s.channel || "Playlist",
    duration: s.duration || 0,
  }));
  addHistory();
  queue = entries;
  queueIndex = Math.min(startIdx, entries.length - 1);
  loadAndPlay(queue[queueIndex]);
  renderQueue();
}

function deletePlaylist(name) {
  if (!window.confirm(`Delete playlist "${name}"?`)) return;
  fetch("/api/playlists/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast(`Deleted "${name}"`);
        playlistSongs.innerHTML = "";
        loadPlaylists();
      } else {
        showToast("Failed: " + (data.error || "Unknown error"));
      }
    })
    .catch(() => showToast("Delete failed"));
}

function removeFromPlaylist(name, index) {
  fetch("/api/playlist/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, index }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast("Removed from playlist");
        loadPlaylists();
        openPlaylist(name);
      } else {
        showToast("Failed: " + (data.error || "Unknown error"));
      }
    })
    .catch(() => showToast("Remove failed"));
}

function createPlaylist(name) {
  return fetch("/api/playlists/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast(`Created "${name}"`);
        loadPlaylists();
        return true;
      }
      showToast("Failed: " + (data.error || "Unknown error"));
      return false;
    })
    .catch(() => {
      showToast("Create failed");
      return false;
    });
}

function addSongToPlaylist(name, track) {
  const song = toPlaylistSong(track);
  fetch("/api/playlist/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, song }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.success) {
        showToast(`Added to "${name}"`);
        loadPlaylists();
      } else {
        showToast("Failed: " + (data.error || "Unknown error"));
      }
    })
    .catch(() => showToast("Add failed"));
}

function openPlaylistMenu(btn, track) {
  closePlaylistMenu();
  const menu = document.createElement("div");
  menu.className = "pl-menu";
  if (!playlistsCache.length) {
    const empty = document.createElement("div");
    empty.className = "pl-menu-empty";
    empty.textContent = "No playlists yet";
    menu.appendChild(empty);
  }
  playlistsCache.forEach((p) => {
    const item = document.createElement("button");
    item.type = "button";
    item.textContent = p.name;
    item.addEventListener("click", (e) => {
      e.stopPropagation();
      closePlaylistMenu();
      addSongToPlaylist(p.name, track);
    });
    menu.appendChild(item);
  });
  const newItem = document.createElement("button");
  newItem.type = "button";
  newItem.className = "pl-menu-new";
  newItem.innerHTML = '<i class="bi bi-plus-lg"></i> New playlist';
  newItem.addEventListener("click", (e) => {
    e.stopPropagation();
    closePlaylistMenu();
    pendingSong = track;
    playlistModalMode = "song";
    playlistModalTitle.innerHTML = '<i class="bi bi-plus-lg"></i> Save to Playlist';
    playlistNameInput.value = "";
    playlistModal.classList.add("open");
    setTimeout(() => playlistNameInput.focus(), 50);
  });
  menu.appendChild(newItem);
  document.body.appendChild(menu);
  const rect = btn.getBoundingClientRect();
  const mw = 180;
  let left = rect.left;
  if (left + mw > window.innerWidth - 8) left = window.innerWidth - mw - 8;
  menu.style.left = left + "px";
  menu.style.top = rect.bottom + 4 + "px";
  setTimeout(() => {
    document.addEventListener("click", closePlaylistMenu, { once: true });
  }, 0);
}

function closePlaylistMenu() {
  document.querySelectorAll(".pl-menu").forEach((m) => m.remove());
}

function loadLiked() {
  fetch("/api/liked")
    .then((r) => r.json())
    .then((data) => {
      const songs = data.results || [];
      const ids = data.liked_ids || [];
      const container = document.getElementById("likedSongs");
      if (!container) return;
      if (songs.length === 0 && ids.length === 0) {
        container.innerHTML =
          '<div style="color: var(--text3); text-align:center; padding: 20px; font-size: 13px;">No liked songs yet.</div>';
        return;
      }
      container.innerHTML = "";
      songs.forEach((item) => {
        const entry = {
          ...item,
          source: "local",
          channel: "Liked Songs",
          thumbnail: "",
        };
        const card = createSongCard(entry, "local");
        card.addEventListener("click", () => playLocal(entry, songs));
        const addBtn = card.querySelector(".song-actions button");
        addBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          addToQueue(entry);
        });
        container.appendChild(card);
      });
      const entries = data.liked_entries || [];
      if (entries.length > 0 && songs.length === 0) {
        entries.forEach((entry) => {
          const item = {
            video_id: entry.video_id,
            title: entry.title || entry.video_id,
            source: "yt",
            channel: "Liked",
            thumbnail: "",
            duration: 0,
          };
          const card = createSongCard(item, "yt");
          card.addEventListener("click", () => playTrack(item));
          const addBtn = card.querySelector(".song-actions button");
          addBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            addToQueue(item);
          });
          container.appendChild(card);
        });
      }
    })
    .catch(() => {});
}


function loadSettings() {
  fetch("/api/settings")
    .then((r) => r.json())
    .then((data) => {
      if (data && Object.keys(data).length > 0) {
        Object.assign(settings, data);
        applySettings();
        updateSettingsUI();
      }
    });
}

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return { r, g, b };
}

function lightenHex(hex, amount) {
  const { r, g, b } = hexToRgb(hex);
  const lr = Math.min(255, r + amount);
  const lg = Math.min(255, g + amount);
  const lb = Math.min(255, b + amount);
  return `#${lr.toString(16).padStart(2, "0")}${lg.toString(16).padStart(2, "0")}${lb.toString(16).padStart(2, "0")}`;
}

function applySettings() {
  document.documentElement.setAttribute("data-theme", settings.theme || "dark");
  const accent = settings.accent || "#6c63ff";
  const { r, g, b } = hexToRgb(accent);
  document.documentElement.style.setProperty("--accent", accent);
  document.documentElement.style.setProperty(
    "--accent2",
    lightenHex(accent, 30),
  );
  document.documentElement.style.setProperty(
    "--accent-glow",
    `rgba(${r},${g},${b},0.3)`,
  );
  document.documentElement.style.setProperty(
    "--bg-blur",
    (settings.bgBlur || 10) + "px",
  );
  document.documentElement.style.setProperty(
    "--bg-dim",
    (settings.bgDim || 60) / 100,
  );
  volumeSlider.value = settings.defaultVolume || 80;
  audio.volume = (settings.defaultVolume || 80) / 100;
  if (settings.defaultSource) setSearchSource(settings.defaultSource);
}

function updateSettingsUI() {
  document.getElementById("setTheme").value = settings.theme || "dark";
  document.getElementById("setAccent").value = settings.accent || "#6c63ff";
  document.getElementById("setBgBlur").value = settings.bgBlur || 10;
  document.getElementById("setBgDim").value = settings.bgDim || 60;
  document.getElementById("setVolume").value = settings.defaultVolume || 80;
  document.getElementById("setCrossfade").value = settings.crossfade || 2;
  document.getElementById("setMiniOnBlur").checked =
    settings.miniOnBlur || false;
  document.getElementById("setDefaultSource").value =
    settings.defaultSource || "youtube";
  document.getElementById("setDownloadPath").value =
    settings.downloadPath || "~/.flow/downloads";
  document.getElementById("setDownloadFormat").value =
    settings.format || "webm";
}

function saveSettingsToAPI() {
  const newSettings = {
    theme: document.getElementById("setTheme").value,
    accent: document.getElementById("setAccent").value,
    bgBlur: parseInt(document.getElementById("setBgBlur").value),
    bgDim: parseInt(document.getElementById("setBgDim").value),
    defaultVolume: parseInt(document.getElementById("setVolume").value),
    crossfade: parseInt(document.getElementById("setCrossfade").value) || 2,
    miniOnBlur: document.getElementById("setMiniOnBlur").checked,
    defaultSource: document.getElementById("setDefaultSource").value,
    downloadPath: document.getElementById("setDownloadPath").value || "~/.flow/downloads",
    format: document.getElementById("setDownloadFormat").value || "webm",
  };
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(newSettings),
  })
    .then((r) => r.json())
    .then((data) => {
      Object.assign(settings, data.settings || newSettings);
      applySettings();
      settingsModal.classList.remove("open");
    });
}

function resetSettings() {
  settings = {
    theme: "dark",
    accent: "#6c63ff",
    bgBlur: 10,
    bgDim: 60,
    defaultVolume: 80,
    crossfade: 2,
    miniOnBlur: false,
    defaultSource: "youtube",
    downloadPath: "~/.flow/downloads",
    format: "webm",
  };
  applySettings();
  updateSettingsUI();
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}

function goMini() {
  playerMain.style.display = "none";
  miniPlayer.style.display = "flex";
}

function showToast(msg, duration) {
  duration = duration || 3000;
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  setTimeout(function () {
    toastEl.classList.remove("show");
  }, duration);
}

function loadLibrary() {
  fetch("/api/library")
    .then((r) => r.json())
    .then((data) => {
      librarySongs = {};
      downloadedIds = new Set();
      (data.songs || []).forEach((s) => {
        librarySongs[s.video_id] = s;
        if (s.downloaded) downloadedIds.add(s.video_id);
      });
      // markDownloadedCards();
    })
    .catch(() => {});
}

// function markDownloadedCards() {
//   document.querySelectorAll(".song-card").forEach((c) => {
//     const id = c.dataset.videoId;
//     const badge = c.querySelector(".downloaded-badge");
//     const has = id && downloadedIds.has(id);
//     if (has && !badge) {
//       const el = document.createElement("span");
//       el.className = "downloaded-badge";
//       el.innerHTML = '<i class="bi bi-check-circle-fill"></i>';
//       el.title = "Downloaded";
//       c.appendChild(el);
//     } else if (!has && badge) {
//       badge.remove();
//     }
//   });
// }

function setDownloadBtnState(downloaded) {
  currentDownloaded = downloaded;
  const icon = downloadBtn.querySelector("i");
  downloadBtn.classList.toggle("downloaded", downloaded);
  icon.className = downloaded ? "bi bi-check-circle" : "bi bi-download";
  downloadBtn.title = downloaded ? "Downloaded - click to remove" : "Download";
}

function checkDownload(videoId) {
  if (!videoId) {
    setDownloadBtnState(false);
    return;
  }
  if (downloadedIds.has(videoId)) {
    setDownloadBtnState(true);
    return;
  }
  fetch(`/api/library`)
    .then((r) => r.json())
    .then((data) => {
      librarySongs = {};
      downloadedIds = new Set();
      (data.songs || []).forEach((s) => {
        librarySongs[s.video_id] = s;
        if (s.downloaded) downloadedIds.add(s.video_id);
      });
      if (downloadedIds.has(videoId)) {
        setDownloadBtnState(true);
        // markDownloadedCards();
      } else {
        setDownloadBtnState(false);
      }
    })
    .catch(() => {});
}

function deleteDownload() {
  if (queueIndex < 0 || !queue[queueIndex]) return;
  var track = queue[queueIndex];
  var vid = track.video_id;
  if (!vid) return;
  if (!window.confirm("Remove this download from your library?")) return;
  fetch("/api/delete-download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_id: vid }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.success) {
        downloadedIds.delete(vid);
        if (librarySongs[vid]) {
          librarySongs[vid].downloaded = false;
          librarySongs[vid].thumbnail = "";
        }
        setDownloadBtnState(false);
        // markDownloadedCards();
        showToast("Removed download");
      } else {
        showToast("Failed: " + (data.error || "Not downloaded"));
      }
    })
    .catch(function () {
      showToast("Failed to remove download");
    });
}

function downloadTrack() {
  if (queueIndex < 0 || !queue[queueIndex]) {
    showToast("No track selected");
    return;
  }
  var track = queue[queueIndex];
  var vid = track.video_id;
  if (!vid) {
    showToast("Cannot download local tracks");
    return;
  }
  if (currentDownloaded) {
    deleteDownload();
    return;
  }
  var saveDir = settings.downloadPath || "~/.flow/downloads";
  downloadBtn.classList.add("downloading");
  showToast("Downloading...");
  fetch("/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_id: vid, save_dir: saveDir, format: settings.format }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      downloadBtn.classList.remove("downloading");
      if (data.success) {
        downloadedIds.add(vid);
        if (librarySongs[vid]) {
          librarySongs[vid].downloaded = true;
          if (data.thumbnail) librarySongs[vid].thumbnail = data.thumbnail;
        } else {
          librarySongs[vid] = {
            video_id: vid,
            title: data.title || track.title || "",
            liked: false,
            downloaded: true,
            thumbnail: data.thumbnail || "",
          };
        }
        setDownloadBtnState(true);
        // markDownloadedCards();
        showToast("Downloaded: " + (data.title || track.title));
      } else {
        showToast("Failed: " + (data.error || "Unknown error"));
      }
    })
    .catch(function () {
      downloadBtn.classList.remove("downloading");
      showToast("Download failed");
    });
}

downloadBtn.addEventListener("click", downloadTrack);

let currentLiked = false;

function checkLiked(videoId) {
  if (!videoId) {
    currentLiked = false;
    likeBtn.querySelector("i").className = "bi bi-heart";
    return;
  }
  const entry = librarySongs[videoId];
  if (entry) {
    currentLiked = entry.liked || false;
    likeBtn.querySelector("i").className = currentLiked
      ? "bi bi-heart-fill"
      : "bi bi-heart";
    return;
  }
  fetch(`/api/library`)
    .then((r) => r.json())
    .then((data) => {
      librarySongs = {};
      downloadedIds = new Set();
      (data.songs || []).forEach((s) => {
        librarySongs[s.video_id] = s;
        if (s.downloaded) downloadedIds.add(s.video_id);
      });
      const e = librarySongs[videoId];
      currentLiked = (e && e.liked) || false;
      likeBtn.querySelector("i").className = currentLiked
        ? "bi bi-heart-fill"
        : "bi bi-heart";
    })
    .catch(() => {});
}

function toggleLike() {
  if (queueIndex < 0 || !queue[queueIndex]) return;
  var track = queue[queueIndex];
  var vid = track.video_id;
  if (!vid) {
    showToast("Cannot like local tracks");
    return;
  }
  fetch("/api/like", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video_id: vid,
      title: track.title || "Unknown",
      save_dir: settings.downloadPath || "~/.flow/downloads",
      format: settings.format,
    }),
  })
    .then((r) => r.json())
    .then((data) => {
      currentLiked = data.liked;
      likeBtn.querySelector("i").className = currentLiked
        ? "bi bi-heart-fill"
        : "bi bi-heart";
      if (librarySongs[vid]) librarySongs[vid].liked = currentLiked;
      else librarySongs[vid] = { video_id: vid, liked: currentLiked, downloaded: false, thumbnail: "" };
      if (currentLiked) {
        showToast("Liked - downloading...");
        pollLikeDownload(vid);
      } else {
        showToast("Removed from liked");
      }
    });
}

function pollLikeDownload(vid) {
  let tries = 0;
  const iv = setInterval(() => {
    tries++;
    if (tries > 60) {
      clearInterval(iv);
      return;
    }
    fetch("/api/library")
      .then((r) => r.json())
      .then((data) => {
        (data.songs || []).forEach((s) => {
          librarySongs[s.video_id] = s;
          if (s.downloaded) downloadedIds.add(s.video_id);
        });
        if (librarySongs[vid] && librarySongs[vid].downloaded) {
          clearInterval(iv);
          setDownloadBtnState(true);
          // markDownloadedCards();
          if (queue[queueIndex] && queue[queueIndex].video_id === vid) {
            updateMiniPlayer(queue[queueIndex]);
            updateBg(effectiveThumb(queue[queueIndex]));
            applyArt(albumArt, queue[queueIndex].thumbnail, queue[queueIndex]);
          }
          showToast("Liked - downloaded");
        }
      })
      .catch(() => {});
  }, 2000);
}

likeBtn.addEventListener("click", toggleLike);

function goFull() {
  miniPlayer.style.display = "none";
  playerMain.style.display = "flex";
}

document.addEventListener("keydown", (e) => {
  if (e.target === searchInput) return;
  switch (e.key) {
    case " ":
    case "k":
      e.preventDefault();
      togglePlay();
      break;
    case "ArrowLeft":
      e.preventDefault();
      audio.currentTime = Math.max(0, audio.currentTime - 5);
      break;
    case "ArrowRight":
      e.preventDefault();
      audio.currentTime = Math.min(audio.duration, audio.currentTime + 5);
      break;
    case "ArrowUp":
      e.preventDefault();
      audio.volume = Math.min(1, audio.volume + 0.1);
      volumeSlider.value = audio.volume * 100;
      break;
    case "ArrowDown":
      e.preventDefault();
      audio.volume = Math.max(0, audio.volume - 0.1);
      volumeSlider.value = audio.volume * 100;
      break;
    case "n":
      nextTrack();
      break;
    case "p":
      prevTrack();
      break;
  }
});

function pollControls() {
  fetch("/api/control/poll")
    .then((r) => r.json())
    .then((data) => {
      const cmd = data.command;
      if (cmd === "next") nextTrack();
      else if (cmd === "previous") prevTrack();
      else if (cmd === "stop" && audio.src) togglePlay();
    })
    .catch(() => {});
}

loadSettings();
setTab("search");
scanLocal();
loadLiked();
loadLibrary();
loadPlaylists();
setInterval(pollControls, 1000);
