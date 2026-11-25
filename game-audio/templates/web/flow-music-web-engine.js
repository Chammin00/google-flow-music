/**
 * Zero-dependency Web Audio adaptive stem controller for Google Flow Music exports.
 * Works across 1st grade learning, My Planetarium, AAC, and HTML5/Canvas studio apps.
 */
export class FlowMusicAdaptiveEngine {
    constructor(options = {}) {
        this.masterVolume = typeof options.masterVolume === 'number' ? options.masterVolume : 0.85;
        this.ctx = null;
        this.masterGain = null;
        this.manifest = null;
        this.buffers = new Map();
        this.stemGains = new Map();
        this.activeSources = [];
        this.isPlaying = false;
        this.currentState = 'exploration';
    }

    async loadManifest(manifestUrl) {
        const res = await fetch(manifestUrl);
        if (!res.ok) {
            throw new Error(`Failed to fetch Flow Music manifest (${res.status}): ${manifestUrl}`);
        }
        this.manifest = await res.json();
        this._ensureContext();

        const baseUrl = new URL('.', new URL(manifestUrl, window.location.href)).href;
        const formatsMap = this.manifest.stemFormats || {};
        const stemsMap = this.manifest.stems || {};
        const useOgg = this._canPlayOgg();

        const entries = Object.keys(stemsMap);
        await Promise.all(entries.map(async (stemName) => {
            const candidates = Array.isArray(formatsMap[stemName]) && formatsMap[stemName].length > 0
                ? formatsMap[stemName]
                : [stemsMap[stemName]];

            const preferred = candidates.find((p) => (useOgg ? p.endsWith('.ogg') : p.endsWith('.mp3'))) || candidates[0];
            const audioUrl = new URL(preferred, baseUrl).href;
            const audioRes = await fetch(audioUrl);
            if (!audioRes.ok) {
                throw new Error(`Failed to load stem ${stemName}: ${audioUrl}`);
            }
            const arrBuf = await audioRes.arrayBuffer();
            const decoded = await this.ctx.decodeAudioData(arrBuf);
            this.buffers.set(stemName, decoded);
        }));

        return this.manifest;
    }

    async start(initialState = 'exploration') {
        this._ensureContext();
        if (this.ctx.state === 'suspended') {
            await this.ctx.resume();
        }
        this.stop();

        const t0 = this.ctx.currentTime + 0.08;
        const loop = this.manifest ? Boolean(this.manifest.loopable) : true;
        const states = (this.manifest && this.manifest.states) ? this.manifest.states : {};
        const initialMix = states[initialState] || {};

        for (const [stemName, buffer] of this.buffers.entries()) {
            const src = this.ctx.createBufferSource();
            src.buffer = buffer;
            src.loop = loop;

            const gainNode = this.ctx.createGain();
            const targetVol = this._getLinearWeight(initialMix, stemName);
            gainNode.gain.setValueAtTime(targetVol, t0);

            src.connect(gainNode);
            gainNode.connect(this.masterGain);
            src.start(t0);

            this.activeSources.push(src);
            this.stemGains.set(stemName, gainNode);
        }

        this.currentState = initialState;
        this.isPlaying = true;
    }

    setState(stateName, fadeSeconds = 1.2) {
        if (!this.manifest || !this.manifest.states || !this.manifest.states[stateName]) {
            return;
        }
        this.currentState = stateName;
        if (!this.ctx || !this.isPlaying) {
            return;
        }

        const now = this.ctx.currentTime;
        const mix = this.manifest.states[stateName];
        for (const [stemName, gainNode] of this.stemGains.entries()) {
            const target = this._getLinearWeight(mix, stemName);
            gainNode.gain.cancelScheduledValues(now);
            gainNode.gain.setValueAtTime(gainNode.gain.value, now);
            gainNode.gain.linearRampToValueAtTime(target, now + Math.max(0.02, fadeSeconds));
        }
    }

    setMasterVolume(volume) {
        this.masterVolume = Math.max(0, Math.min(1, volume));
        if (this.masterGain && this.ctx) {
            this.masterGain.gain.setTargetAtTime(this.masterVolume, this.ctx.currentTime, 0.03);
        }
    }

    stop() {
        for (const src of this.activeSources) {
            try {
                src.stop();
            } catch (_) {
                // Source may have already finished.
            }
        }
        this.activeSources = [];
        this.stemGains.clear();
        this.isPlaying = false;
    }

    _ensureContext() {
        if (!this.ctx) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            this.ctx = new AudioCtx();
            this.masterGain = this.ctx.createGain();
            this.masterGain.gain.value = this.masterVolume;
            this.masterGain.connect(this.ctx.destination);
        }
    }

    _getLinearWeight(mix, stemName) {
        const entry = mix[stemName];
        if (entry && typeof entry.linear === 'number') {
            return Math.max(0, Math.min(1, entry.linear));
        }
        return 0;
    }

    _canPlayOgg() {
        const probe = document.createElement('audio');
        return Boolean(probe.canPlayType && probe.canPlayType('audio/ogg; codecs="vorbis"'));
    }
}
