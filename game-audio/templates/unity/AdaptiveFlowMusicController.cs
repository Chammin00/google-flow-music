using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace FlowMusic
{
    /// <summary>
    /// Drop-in Unity 6 adaptive vertical-remixing controller for Google Flow Music 4-stem exports.
    /// Uses AudioSettings.dspTime + PlayScheduled so all stem AudioSources remain sample-locked.
    /// </summary>
    public class AdaptiveFlowMusicController : MonoBehaviour
    {
        public enum MusicState
        {
            Exploration,
            Tension,
            Combat,
            Climax
        }

        [Header("Flow Music Stems (44.1 kHz aligned WAV)")]
        public AudioClip instrumentsClip;
        public AudioClip bassClip;
        public AudioClip drumsClip;
        public AudioClip vocalsClip;

        [Header("Playback Settings")]
        [Range(0f, 1f)] public float masterVolume = 0.85f;
        public bool loop = true;
        public bool playOnStart = true;
        public MusicState initialState = MusicState.Exploration;

        private readonly Dictionary<string, AudioSource> _sources = new Dictionary<string, AudioSource>();
        private readonly Dictionary<string, float> _stemWeights = new Dictionary<string, float>();
        private Coroutine _fadeRoutine;

        private void Awake()
        {
            CreateStemSource("instruments", instrumentsClip);
            CreateStemSource("bass", bassClip);
            CreateStemSource("drums", drumsClip);
            CreateStemSource("vocals", vocalsClip);
            ApplyStateWeightsImmediate(initialState);
        }

        private void Start()
        {
            if (playOnStart)
            {
                PlaySynced();
            }
        }

        public void PlaySynced()
        {
            double startTime = AudioSettings.dspTime + 0.15;
            foreach (var kvp in _sources)
            {
                if (kvp.Value.clip == null) continue;
                kvp.Value.Stop();
                kvp.Value.PlayScheduled(startTime);
            }
        }

        public void StopAll()
        {
            foreach (var kvp in _sources)
            {
                kvp.Value.Stop();
            }
        }

        public void SetState(MusicState state, float fadeSeconds = 1.2f)
        {
            if (_fadeRoutine != null)
            {
                StopCoroutine(_fadeRoutine);
            }

            if (fadeSeconds <= 0.01f)
            {
                ApplyStateWeightsImmediate(state);
                return;
            }

            _fadeRoutine = StartCoroutine(FadeToState(state, fadeSeconds));
        }

        private void CreateStemSource(string key, AudioClip clip)
        {
            var child = new GameObject($"FlowStem_{key}");
            child.transform.SetParent(transform, false);

            var src = child.AddComponent<AudioSource>();
            src.clip = clip;
            src.loop = loop;
            src.playOnAwake = false;
            src.spatialBlend = 0f;
            src.volume = 0f;

            _sources[key] = src;
            _stemWeights[key] = 0f;
        }

        private static Dictionary<string, float> GetWeightsForState(MusicState state)
        {
            switch (state)
            {
                case MusicState.Exploration:
                    return new Dictionary<string, float>
                    {
                        { "instruments", 1.0f }, { "bass", 0.45f }, { "drums", 0.0f }, { "vocals", 0.0f }
                    };
                case MusicState.Tension:
                    return new Dictionary<string, float>
                    {
                        { "instruments", 1.0f }, { "bass", 0.85f }, { "drums", 0.45f }, { "vocals", 0.0f }
                    };
                case MusicState.Combat:
                    return new Dictionary<string, float>
                    {
                        { "instruments", 1.0f }, { "bass", 1.0f }, { "drums", 1.0f }, { "vocals", 0.0f }
                    };
                case MusicState.Climax:
                    return new Dictionary<string, float>
                    {
                        { "instruments", 1.0f }, { "bass", 1.0f }, { "drums", 1.0f }, { "vocals", 1.0f }
                    };
                default:
                    return new Dictionary<string, float>
                    {
                        { "instruments", 1.0f }, { "bass", 0.5f }, { "drums", 0.0f }, { "vocals", 0.0f }
                    };
            }
        }

        private void ApplyStateWeightsImmediate(MusicState state)
        {
            var targets = GetWeightsForState(state);
            foreach (var kvp in targets)
            {
                _stemWeights[kvp.Key] = kvp.Value;
                if (_sources.TryGetValue(kvp.Key, out var src))
                {
                    src.volume = kvp.Value * masterVolume;
                }
            }
        }

        private IEnumerator FadeToState(MusicState state, float duration)
        {
            var starts = new Dictionary<string, float>(_stemWeights);
            var targets = GetWeightsForState(state);
            float elapsed = 0f;

            while (elapsed < duration)
            {
                elapsed += Time.unscaledDeltaTime;
                float t = Mathf.Clamp01(elapsed / duration);
                foreach (var kvp in targets)
                {
                    float startVal = starts.TryGetValue(kvp.Key, out var v) ? v : 0f;
                    float w = Mathf.Lerp(startVal, kvp.Value, t);
                    _stemWeights[kvp.Key] = w;
                    if (_sources.TryGetValue(kvp.Key, out var src))
                    {
                        src.volume = w * masterVolume;
                    }
                }
                yield return null;
            }

            ApplyStateWeightsImmediate(state);
            _fadeRoutine = null;
        }
    }
}
