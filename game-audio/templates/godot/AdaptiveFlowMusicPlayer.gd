extends Node
class_name AdaptiveFlowMusicPlayer

## Drop-in Godot 4 adaptive vertical-remixing controller for Google Flow Music stems.
## Uses AudioStreamSynchronized so all 4 stems stay sample-accurate across states.

@export var manifest_path: String = "res://assets/audio/flow_music/game-shattered-pagoda-duel/adaptive_manifest.json"
@export var bus_name: String = "Music"
@export var default_state: String = "exploration"
@export var auto_play: bool = true

const STEM_ORDER: Array[String] = ["instruments", "bass", "drums", "vocals"]

var _player: AudioStreamPlayer
var _sync_stream: AudioStreamSynchronized
var _stem_indices: Dictionary = {}
var _states: Dictionary = {}
var _current_tween: Tween


func _ready() -> void:
	_player = AudioStreamPlayer.new()
	_player.bus = bus_name
	add_child(_player)

	if not manifest_path.is_empty() and FileAccess.file_exists(manifest_path):
		load_from_manifest(manifest_path)
		if auto_play:
			play_state(default_state, 0.0)


func load_from_manifest(path: String) -> bool:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_warning("AdaptiveFlowMusicPlayer: Unable to open manifest: %s" % path)
		return false

	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("AdaptiveFlowMusicPlayer: Invalid manifest JSON: %s" % path)
		return false

	var base_dir := path.get_base_dir()
	var stems_dict: Dictionary = parsed.get("stems", {})
	_states = parsed.get("states", {})

	_sync_stream = AudioStreamSynchronized.new()
	_stem_indices.clear()

	var slot := 0
	for stem_name in STEM_ORDER:
		if not stems_dict.has(stem_name):
			continue
		var rel_path: String = str(stems_dict[stem_name])
		var res_path := base_dir.path_join(rel_path)
		if not ResourceLoader.exists(res_path):
			push_warning("AdaptiveFlowMusicPlayer: Missing stem resource: %s" % res_path)
			continue

		var stream := ResourceLoader.load(res_path) as AudioStream
		if stream == null:
			continue

		if stream is AudioStreamOggVorbis:
			(stream as AudioStreamOggVorbis).loop = bool(parsed.get("loopable", true))

		_sync_stream.stream_count = slot + 1
		_sync_stream.set_sync_stream(slot, stream)
		_sync_stream.set_sync_stream_volume(slot, -80.0)
		_stem_indices[stem_name] = slot
		slot += 1

	_player.stream = _sync_stream
	return slot > 0


func play_state(state_name: String = "exploration", fade_sec: float = 0.0) -> void:
	if _sync_stream == null:
		return
	if not _player.playing:
		_player.play()
	set_music_state(state_name, fade_sec)


func set_music_state(state_name: String, fade_sec: float = 1.2) -> void:
	if _sync_stream == null or not _states.has(state_name):
		return

	if _current_tween != null and _current_tween.is_valid():
		_current_tween.kill()

	var target_mix: Dictionary = _states[state_name]
	if fade_sec <= 0.01:
		for stem_name in _stem_indices.keys():
			var idx: int = _stem_indices[stem_name]
			var target_db := _get_target_db(target_mix, stem_name)
			_sync_stream.set_sync_stream_volume(idx, target_db)
		return

	_current_tween = create_tween().set_parallel(true)
	for stem_name in _stem_indices.keys():
		var idx: int = _stem_indices[stem_name]
		var start_db := _sync_stream.get_sync_stream_volume(idx)
		var end_db := _get_target_db(target_mix, stem_name)
		_current_tween.tween_method(
			func(val: float) -> void: _sync_stream.set_sync_stream_volume(idx, val),
			start_db,
			end_db,
			fade_sec
		)


func _get_target_db(mix: Dictionary, stem_name: String) -> float:
	if not mix.has(stem_name):
		return -80.0
	var entry = mix[stem_name]
	if typeof(entry) == TYPE_DICTIONARY and entry.has("db"):
		return clampf(float(entry["db"]), -80.0, 0.0)
	return -80.0
