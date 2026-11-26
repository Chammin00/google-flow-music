/* Google Flow Music — Web Audio Gapless Audition & Catalog Engine */
(function () {
  'use strict';

  const DUCK_LINEAR = 0.281838; // 10^(-11/20) for -11 dB BUS_DIALOGUE sidechain simulation

  const state = {
    catalog: null,
    tracks: [],
    selectedSlug: null,
    filterCategory: 'all',
    loopableOnly: false,
    searchQuery: '',
    sortBy: 'slug',
    loopEnabled: true,
    duckEnabled: false,
    volume: 0.82,
    isPlaying: false,
    isLoadingAudio: false,
    durationSec: 0,
    pausedOffset: 0,
    startedAtCtx: 0,
    startedOffset: 0,
    playGeneration: 0,
    rafId: null,
  };

  let audioCtx = null;
  let duckGain = null;
  let masterGain = null;
  let currentSource = null;
  const decodedCache = new Map();

  const els = {
    statCount: document.getElementById('stat-track-count'),
    statLufs: document.getElementById('stat-avg-lufs'),
    statRom: document.getElementById('stat-rom-sync'),
    statDc13: document.getElementById('stat-dc13-sync'),
    dotRom: document.getElementById('dot-rom'),
    dotDc13: document.getElementById('dot-dc13'),
    btnRescan: document.getElementById('btn-rescan'),
    btnSyncAll: document.getElementById('btn-sync-all'),
    deckSlug: document.getElementById('deck-slug'),
    deckStatusTag: document.getElementById('deck-status-tag'),
    deckTitle: document.getElementById('deck-title'),
    deckBpm: document.getElementById('deck-bpm'),
    deckKey: document.getElementById('deck-key'),
    deckLufs: document.getElementById('deck-lufs'),
    deckTp: document.getElementById('deck-tp'),
    deckLoopBadge: document.getElementById('deck-loop-badge'),
    waveformWrap: document.getElementById('waveform-wrap'),
    waveformCanvas: document.getElementById('waveform-canvas'),
    deckTimeCur: document.getElementById('deck-time-cur'),
    deckFrameCur: document.getElementById('deck-frame-cur'),
    btnPlay: document.getElementById('btn-play'),
    btnPlayLabel: document.getElementById('btn-play-label'),
    btnLoopToggle: document.getElementById('btn-loop-toggle'),
    btnLoopLabel: document.getElementById('btn-loop-label'),
    btnSeamTest: document.getElementById('btn-seam-test'),
    btnDuckToggle: document.getElementById('btn-duck-toggle'),
    btnDuckLabel: document.getElementById('btn-duck-label'),
    volSlider: document.getElementById('vol-slider'),
    categoryTabs: document.getElementById('category-tabs'),
    btnLoopFilter: document.getElementById('btn-loop-filter'),
    searchInput: document.getElementById('search-input'),
    sortSelect: document.getElementById('sort-select'),
    tbody: document.getElementById('catalog-tbody'),
    inspCategory: document.getElementById('insp-category'),
    inspBpm: document.getElementById('insp-bpm'),
    inspKey: document.getElementById('insp-key'),
    inspLufs: document.getElementById('insp-lufs'),
    inspFrames: document.getElementById('insp-frames'),
    inspSr: document.getElementById('insp-sr'),
    inspSha: document.getElementById('insp-sha'),
    inspCueNotes: document.getElementById('insp-cue-notes'),
    inspSyncBadge: document.getElementById('insp-sync-badge'),
    inspRightsBanner: document.getElementById('insp-rights-banner'),
    inspYtRole: document.getElementById('insp-yt-role'),
    inspDestPath: document.getElementById('insp-dest-path'),
    inspInvideoJson: document.getElementById('insp-invideo-json'),
    btnCopyInvideo: document.getElementById('btn-copy-invideo'),
    footerStatus: document.getElementById('footer-status'),
  };

  function ensureAudioContext() {
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      audioCtx = new AC();
      duckGain = audioCtx.createGain();
      masterGain = audioCtx.createGain();
      duckGain.gain.value = state.duckEnabled ? DUCK_LINEAR : 1.0;
      masterGain.gain.value = state.volume;
      duckGain.connect(masterGain);
      masterGain.connect(audioCtx.destination);
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }
  }

  function formatTime(sec) {
    const s = Math.max(0, Number(sec) || 0);
    const m = Math.floor(s / 60);
    const rem = s - m * 60;
    const whole = Math.floor(rem);
    const cs = Math.floor((rem - whole) * 100);
    return `${String(m).padStart(2, '0')}:${String(whole).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
  }

  function getSelectedTrack() {
    return state.tracks.find((t) => t.slug === state.selectedSlug) || null;
  }

  function stopSourceNode() {
    if (currentSource) {
      try {
        currentSource.onended = null;
        currentSource.stop();
        currentSource.disconnect();
      } catch (_err) {
        // Ignore already-stopped source nodes
      }
      currentSource = null;
    }
  }

  function getCurrentPlayhead() {
    const dur = Math.max(0.001, state.durationSec || 1);
    if (!state.isPlaying || !audioCtx) {
      return Math.min(dur, Math.max(0, state.pausedOffset));
    }
    const elapsed = Math.max(0, audioCtx.currentTime - state.startedAtCtx);
    const rawPos = state.startedOffset + elapsed;
    if (state.loopEnabled) {
      return rawPos % dur;
    }
    if (rawPos >= dur) {
      return dur;
    }
    return rawPos;
  }

  async function loadAudioBuffer(track) {
    if (decodedCache.has(track.slug)) {
      return decodedCache.get(track.slug);
    }
    ensureAudioContext();
    setDeckTag('LOADING', 'tag-amber');
    state.isLoadingAudio = true;
    try {
      const resp = await fetch(track.audio_url);
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status} loading ${track.audio_url}`);
      }
      const arr = await resp.arrayBuffer();
      const buf = await audioCtx.decodeAudioData(arr);
      decodedCache.set(track.slug, buf);
      return buf;
    } finally {
      state.isLoadingAudio = false;
    }
  }

  async function startPlayback(track, startAtSec) {
    const gen = ++state.playGeneration;
    ensureAudioContext();
    stopSourceNode();

    try {
      const buf = await loadAudioBuffer(track);
      if (gen !== state.playGeneration || state.selectedSlug !== track.slug) {
        return;
      }
      const dur = buf.duration || track.duration_sec;
      state.durationSec = dur;
      const offset = Math.max(0, Math.min(Math.max(0, dur - 0.02), startAtSec || 0));

      const src = audioCtx.createBufferSource();
      src.buffer = buf;
      src.loop = state.loopEnabled;
      src.loopStart = 0;
      src.loopEnd = dur;
      src.connect(duckGain);

      src.onended = () => {
        if (currentSource === src && !state.loopEnabled && gen === state.playGeneration) {
          state.isPlaying = false;
          state.pausedOffset = 0;
          currentSource = null;
          updatePlayButtonUI();
          drawWaveformAndReadout();
        }
      };

      src.start(0, offset);
      currentSource = src;
      state.isPlaying = true;
      state.startedAtCtx = audioCtx.currentTime;
      state.startedOffset = offset;
      state.pausedOffset = offset;
      setDeckTag('PLAYING', 'tag-green');
      updatePlayButtonUI();
      startAnimationLoop();
    } catch (err) {
      state.isPlaying = false;
      setDeckTag('ERROR', 'tag-amber');
      els.footerStatus.textContent = `Audio decode error: ${err.message}`;
      updatePlayButtonUI();
    }
  }

  function pausePlayback() {
    if (!state.isPlaying) return;
    state.pausedOffset = getCurrentPlayhead();
    stopSourceNode();
    state.isPlaying = false;
    setDeckTag('PAUSED', 'tag-blue');
    updatePlayButtonUI();
    drawWaveformAndReadout();
  }

  function togglePlayPause() {
    const track = getSelectedTrack();
    if (!track) return;
    if (state.isPlaying) {
      pausePlayback();
    } else {
      const resumeAt = state.pausedOffset >= Math.max(0, state.durationSec - 0.05) ? 0 : state.pausedOffset;
      startPlayback(track, resumeAt);
    }
  }

  function seekTo(targetSec) {
    const track = getSelectedTrack();
    if (!track) return;
    const dur = Math.max(0.1, state.durationSec || track.duration_sec || 1);
    const clamped = Math.max(0, Math.min(dur - 0.02, targetSec));
    state.pausedOffset = clamped;
    if (state.isPlaying) {
      startPlayback(track, clamped);
    } else {
      drawWaveformAndReadout();
    }
  }

  function jumpToSeamTest() {
    const track = getSelectedTrack();
    if (!track) return;
    if (!state.loopEnabled) {
      state.loopEnabled = true;
      syncLoopUI();
    }
    const dur = state.durationSec || track.duration_sec;
    const seamStart = Math.max(0, dur - 4.0);
    els.footerStatus.textContent = `Auditioning circular seam (${formatTime(seamStart)} -> ${formatTime(dur)} -> 00:00.00) on ${track.slug}`;
    startPlayback(track, seamStart);
  }

  function toggleLoop() {
    state.loopEnabled = !state.loopEnabled;
    if (currentSource) {
      currentSource.loop = state.loopEnabled;
      currentSource.loopStart = 0;
      currentSource.loopEnd = state.durationSec || (currentSource.buffer ? currentSource.buffer.duration : 0);
    }
    syncLoopUI();
  }

  function syncLoopUI() {
    els.btnLoopLabel.textContent = state.loopEnabled ? 'Loop: ON' : 'Loop: OFF';
    els.btnLoopToggle.classList.toggle('btn-active', state.loopEnabled);
  }

  function toggleDuck() {
    state.duckEnabled = !state.duckEnabled;
    if (duckGain && audioCtx) {
      duckGain.gain.setTargetAtTime(state.duckEnabled ? DUCK_LINEAR : 1.0, audioCtx.currentTime, 0.035);
    }
    els.btnDuckLabel.textContent = state.duckEnabled ? 'Duck -11 dB: ON' : 'Duck -11 dB: OFF';
    els.btnDuckToggle.classList.toggle('btn-duck-active', state.duckEnabled);
  }

  function setDeckTag(text, cls) {
    els.deckStatusTag.textContent = text;
    els.deckStatusTag.className = `tag ${cls || ''}`.trim();
  }

  function updatePlayButtonUI() {
    els.btnPlayLabel.textContent = state.isPlaying ? 'Pause' : 'Play';
  }

  function drawWaveformAndReadout() {
    const canvas = els.waveformCanvas;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const track = getSelectedTrack();
    const dur = track ? (state.durationSec || track.duration_sec || 1) : 1;
    const pos = track ? getCurrentPlayhead() : 0;
    const progress = Math.max(0, Math.min(1, pos / dur));

    // Grid baseline + seam zone highlight (last 4s)
    ctx.fillStyle = '#010409';
    ctx.fillRect(0, 0, w, h);

    if (track && dur > 4.5) {
      const seamX = ((dur - 4.0) / dur) * w;
      ctx.fillStyle = 'rgba(240, 136, 62, 0.08)';
      ctx.fillRect(seamX, 0, w - seamX, h);
    }

    const peaks = (track && track.waveform_peaks) || [];
    const n = peaks.length || 120;
    const barW = w / n;
    const midY = h / 2;

    for (let i = 0; i < n; i++) {
      const val = peaks[i] !== undefined ? peaks[i] : 0.2;
      const barH = Math.max(4, val * (h - 12));
      const x = i * barW;
      const ratio = (i + 0.5) / n;
      ctx.fillStyle = ratio <= progress ? '#f0883e' : '#30363d';
      ctx.fillRect(x + 1, midY - barH / 2, Math.max(2, barW - 2.2), barH);
    }

    // Playhead cursor
    if (track) {
      const px = Math.round(progress * w);
      ctx.fillStyle = '#58a6ff';
      ctx.fillRect(px, 0, 2, h);
    }

    els.deckTimeCur.textContent = `${formatTime(pos)} / ${formatTime(dur)}`;
    const curFrame = Math.round(pos * 24);
    const totalFrames = Math.round(dur * 24);
    els.deckFrameCur.textContent = `24fps f: ${curFrame} / ${totalFrames}`;
  }

  function startAnimationLoop() {
    if (state.rafId !== null) cancelAnimationFrame(state.rafId);
    const tick = () => {
      drawWaveformAndReadout();
      if (state.isPlaying) {
        state.rafId = requestAnimationFrame(tick);
      } else {
        state.rafId = null;
      }
    };
    state.rafId = requestAnimationFrame(tick);
  }

  function selectTrack(slug, autoPlay) {
    const track = state.tracks.find((t) => t.slug === slug);
    if (!track) return;

    const changed = state.selectedSlug !== slug;
    state.selectedSlug = slug;
    state.durationSec = track.duration_sec;

    if (changed) {
      stopSourceNode();
      state.isPlaying = false;
      state.pausedOffset = 0;
      state.playGeneration++;
      setDeckTag('READY', 'tag-blue');
      updatePlayButtonUI();
    }

    // Populate Deck Header
    els.deckSlug.textContent = track.slug.toUpperCase();
    els.deckTitle.textContent = track.title;
    els.deckBpm.textContent = `${track.bpm} BPM`;
    els.deckKey.textContent = track.key;
    els.deckLufs.textContent = `${track.integrated_lufs.toFixed(2)} LUFS`;
    els.deckTp.textContent = `TP ${track.true_peak_db.toFixed(2)} dB`;
    els.deckLoopBadge.textContent = track.loopable ? 'CIRCULAR LOOP' : 'SUITE / BLEND';
    els.deckLoopBadge.className = track.loopable ? 'tag tag-green' : 'tag';

    // Populate Inspector
    els.inspCategory.textContent = track.category_label;
    els.inspBpm.textContent = `${track.bpm} BPM (${track.time_signature})`;
    els.inspKey.textContent = track.key;
    els.inspLufs.textContent = `${track.integrated_lufs.toFixed(2)} LUFS / TP ${track.true_peak_db.toFixed(2)} dB`;
    els.inspFrames.textContent = `${track.frames_24fps} frames (${track.duration_sec.toFixed(2)}s)`;
    els.inspSr.textContent = `${(track.sample_rate / 1000).toFixed(1)} kHz / ${Math.round(track.bit_rate / 1000)} kbps`;
    els.inspSha.textContent = track.sha256.slice(0, 16);
    els.inspCueNotes.textContent = track.cue_notes || track.genre;

    const dep = track.deployment;
    els.inspSyncBadge.textContent = dep.in_sync ? 'SYNCED' : (dep.target_key === 'hub_only' ? 'HUB VAULT' : 'OUT OF SYNC');
    els.inspSyncBadge.className = dep.in_sync ? 'tag tag-green' : 'tag tag-amber';
    els.inspRightsBanner.textContent = track.synth_id_verified
      ? 'Original SynthID-verified Google Flow Music track — cleared for commercial monetization.'
      : 'synthIdVerified: false — External OST/mashup reference blend. Replace with original Google Flow Music master before commercial YouTube monetization.';
    els.inspYtRole.textContent = track.invideo.youtube_role;
    els.inspDestPath.textContent = dep.dest_path || track.source_path;

    const invideoSnippet = {
      clip_id: track.slug,
      source: track.deployment.dest_path || track.source_path,
      bus_id: track.invideo.bus,
      duck_behind_dialogue_db: track.invideo.duck_db,
      target_lufs: track.integrated_lufs,
      cue_windows: track.invideo.cue_windows,
    };
    els.inspInvideoJson.textContent = JSON.stringify(invideoSnippet, null, 2);

    renderTable();
    drawWaveformAndReadout();

    if (autoPlay) {
      startPlayback(track, 0);
    }
  }

  function getFilteredTracks() {
    const q = state.searchQuery.trim().toLowerCase();
    const list = state.tracks.filter((t) => {
      if (state.filterCategory !== 'all' && t.category !== state.filterCategory) return false;
      if (state.loopableOnly && !t.loopable) return false;
      if (q) {
        const hay = `${t.slug} ${t.title} ${t.bpm} ${t.key} ${t.category_label} ${t.genre}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    list.sort((a, b) => {
      if (state.sortBy === 'bpm_desc') return b.bpm - a.bpm;
      if (state.sortBy === 'bpm_asc') return a.bpm - b.bpm;
      if (state.sortBy === 'lufs_desc') return b.integrated_lufs - a.integrated_lufs;
      if (state.sortBy === 'dur_desc') return b.duration_sec - a.duration_sec;
      return a.slug.localeCompare(b.slug);
    });
    return list;
  }

  function renderTable() {
    const rows = getFilteredTracks();
    els.tbody.innerHTML = '';

    for (const t of rows) {
      const tr = document.createElement('tr');
      if (t.slug === state.selectedSlug) {
        tr.classList.add('selected-row');
      }

      const dep = t.deployment;
      const depClass = dep.target_key === 'hub_only' ? 'tag' : (dep.in_sync ? 'tag tag-green' : 'tag tag-amber');
      const shortKey = String(t.key || '').length > 18 ? String(t.key).split('->')[0].trim() + ' +' : t.key;
      const shortTarget = dep.target_key === 'rom_studio_3d'
        ? (dep.in_sync ? `ROM (${dep.target_label.match(/\(([^)]+)\)/)?.[1] || '3d'})` : 'ROM Stale')
        : dep.target_key === 'dead_channel_13'
          ? (dep.in_sync ? 'DC13 Synced' : 'DC13 Stale')
          : 'Hub Vault';

      tr.innerHTML = `
        <td>
          <div class="track-slug-main">${t.slug}</div>
          <div class="track-title-sub" title="${t.title}">${t.title}</div>
        </td>
        <td><span class="tag">${t.category_label}</span></td>
        <td class="cell-mono">${t.bpm}</td>
        <td class="cell-mono" title="${t.key}">${shortKey}</td>
        <td class="cell-mono">
          <div>${t.integrated_lufs.toFixed(2)}</div>
          <div class="cell-sub-mono">TP ${t.true_peak_db.toFixed(2)}</div>
        </td>
        <td class="cell-mono">${formatTime(t.duration_sec)}</td>
        <td><span class="tag ${t.loopable ? 'tag-green' : ''}">${t.loopable ? 'LOOP' : 'SUITE'}</span></td>
        <td><span class="${depClass}" title="${dep.target_label}">${shortTarget}</span></td>
        <td>
          <div style="display:flex;gap:4px;">
            <button class="btn btn-sm btn-row-play" type="button">Play</button>
            <button class="btn btn-sm btn-row-seam" type="button">Seam</button>
          </div>
        </td>
      `;

      tr.addEventListener('click', (e) => {
        if (e.target.closest('.btn-row-play')) {
          selectTrack(t.slug, true);
          return;
        }
        if (e.target.closest('.btn-row-seam')) {
          selectTrack(t.slug, false);
          jumpToSeamTest();
          return;
        }
        selectTrack(t.slug, false);
      });

      els.tbody.appendChild(tr);
    }
  }

  function updateHeaderTelemetry(cat) {
    els.statCount.textContent = String(cat.track_count);
    els.statLufs.textContent = `${cat.avg_lufs.toFixed(2)} LUFS`;
    const rom = cat.sync_summary.rom_studio_3d;
    const dc13 = cat.sync_summary.dead_channel_13;
    els.statRom.textContent = `${rom.synced}/${rom.total}`;
    els.statDc13.textContent = `${dc13.synced}/${dc13.total}`;
    els.dotRom.classList.toggle('warn', rom.synced < rom.total);
    els.dotDc13.classList.toggle('warn', dc13.synced < dc13.total);
  }

  async function fetchCatalog(refresh) {
    const url = refresh ? '/api/catalog?refresh=1' : '/api/catalog';
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} loading catalog`);
    const cat = await resp.json();
    state.catalog = cat;
    state.tracks = cat.tracks || [];
    updateHeaderTelemetry(cat);

    const firstValid = state.selectedSlug && state.tracks.some((t) => t.slug === state.selectedSlug)
      ? state.selectedSlug
      : (state.tracks.find((t) => t.slug.startsWith('rom01')) || state.tracks[0])?.slug;

    if (firstValid) {
      selectTrack(firstValid, false);
    } else {
      renderTable();
      drawWaveformAndReadout();
    }
  }

  async function triggerSyncAll() {
    els.btnSyncAll.disabled = true;
    els.footerStatus.textContent = 'Running Sync-FlowMusicBridge.ps1 across 3D ROM Studio and Dead Channel 13...';
    try {
      const resp = await fetch('/api/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: 'All', force: false }),
      });
      const data = await resp.json();
      if (!resp.ok || data.status !== 'ok') {
        throw new Error(data.stderr || data.error || 'Sync failed');
      }
      await fetchCatalog(false);
      const b = data.bridge;
      els.footerStatus.textContent = `Sync complete: 3D ROM Studio (synced=${b.RomStudioSynced}, upToDate=${b.RomStudioUpToDate}), Dead Channel 13 (encoded=${b.DeadChannelEncoded}, previews=${b.PreviewsSynced + b.PreviewsUpToDate})`;
    } catch (err) {
      els.footerStatus.textContent = `Sync failed: ${err.message}`;
    } finally {
      els.btnSyncAll.disabled = false;
    }
  }

  function bindEvents() {
    els.btnPlay.addEventListener('click', togglePlayPause);
    els.btnLoopToggle.addEventListener('click', toggleLoop);
    els.btnSeamTest.addEventListener('click', jumpToSeamTest);
    els.btnDuckToggle.addEventListener('click', toggleDuck);

    els.volSlider.addEventListener('input', (e) => {
      state.volume = Number(e.target.value);
      if (masterGain && audioCtx) {
        masterGain.gain.setTargetAtTime(state.volume, audioCtx.currentTime, 0.02);
      }
    });

    els.waveformWrap.addEventListener('click', (e) => {
      const track = getSelectedTrack();
      if (!track) return;
      const rect = els.waveformWrap.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      seekTo(ratio * (state.durationSec || track.duration_sec));
    });

    els.categoryTabs.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      if (btn.id === 'btn-loop-filter') {
        state.loopableOnly = !state.loopableOnly;
        btn.classList.toggle('active', state.loopableOnly);
        renderTable();
        return;
      }
      const cat = btn.getAttribute('data-cat');
      if (!cat) return;
      state.filterCategory = cat;
      els.categoryTabs.querySelectorAll('[data-cat]').forEach((el) => {
        el.classList.toggle('active', el.getAttribute('data-cat') === cat);
      });
      renderTable();
    });

    els.searchInput.addEventListener('input', (e) => {
      state.searchQuery = e.target.value;
      renderTable();
    });

    els.sortSelect.addEventListener('change', (e) => {
      state.sortBy = e.target.value;
      renderTable();
    });

    els.btnRescan.addEventListener('click', async () => {
      els.btnRescan.disabled = true;
      els.footerStatus.textContent = 'Re-scanning exports/hits/ MP3s via FFprobe & loudnorm...';
      try {
        await fetchCatalog(true);
        els.footerStatus.textContent = 'Catalog rescanned cleanly.';
      } catch (err) {
        els.footerStatus.textContent = `Rescan error: ${err.message}`;
      } finally {
        els.btnRescan.disabled = false;
      }
    });

    els.btnSyncAll.addEventListener('click', triggerSyncAll);

    els.btnCopyInvideo.addEventListener('click', () => {
      navigator.clipboard.writeText(els.inspInvideoJson.textContent).then(() => {
        els.footerStatus.textContent = `Copied invideo-timeline JSON cue for ${state.selectedSlug}`;
      }).catch(() => {});
    });

    window.addEventListener('keydown', (e) => {
      if (document.activeElement === els.searchInput) return;
      if (e.code === 'Space') {
        e.preventDefault();
        togglePlayPause();
      } else if (e.key === 'l' || e.key === 'L') {
        toggleLoop();
      } else if (e.key === 'j' || e.key === 'J') {
        jumpToSeamTest();
      } else if (e.key === 'd' || e.key === 'D') {
        toggleDuck();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindEvents();
    fetchCatalog(false).catch((err) => {
      els.footerStatus.textContent = `Failed to load catalog: ${err.message}`;
    });
  });
})();
