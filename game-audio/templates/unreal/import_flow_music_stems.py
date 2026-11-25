"""
Unreal Engine 5 Editor Python Importer for Google Flow Music Stems.

Compatible with `game-studio` MCP (`unreal_execute_python`) or UE5 Python Script Editor.
Reads an exported `adaptive_manifest.json`, batch-imports all 48 kHz WAV stems into
`/Game/Audio/FlowMusic/<slug>`, sets `bLooping` on SoundWave assets, and saves packages.
"""

import json
import os
import unreal


def import_flow_music_track(manifest_path: str, content_root: str = "/Game/Audio/FlowMusic") -> dict:
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"adaptive_manifest.json not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8-sig") as f:
        manifest = json.load(f)

    slug = manifest["slug"]
    loopable = bool(manifest.get("loopable", True))
    base_dir = os.path.dirname(os.path.abspath(manifest_path))
    dest_path = f"{content_root}/{slug}"

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    tasks = []
    files_to_import = []

    stems = manifest.get("stems", {})
    for stem_name, rel_path in stems.items():
        abs_file = os.path.normpath(os.path.join(base_dir, rel_path))
        if not os.path.exists(abs_file):
            unreal.log_warning(f"Missing Flow Music stem file: {abs_file}")
            continue

        task = unreal.AssetImportTask()
        task.filename = abs_file
        task.destination_path = dest_path
        task.destination_name = f"SW_{slug}_{stem_name}"
        task.replace_existing = True
        task.automated = True
        task.save = True
        tasks.append(task)
        files_to_import.append(abs_file)

    if not tasks:
        return {"imported": 0, "destination": dest_path, "assets": []}

    asset_tools.import_asset_tasks(tasks)

    imported_assets = []
    for task in tasks:
        for obj_path in task.imported_object_paths:
            asset = unreal.EditorAssetLibrary.load_asset(obj_path)
            if isinstance(asset, unreal.SoundWave):
                asset.set_editor_property("bLooping", loopable)
                unreal.EditorAssetLibrary.save_loaded_asset(asset)
                imported_assets.append(obj_path)

    return {
        "slug": slug,
        "imported": len(imported_assets),
        "destination": dest_path,
        "loopable": loopable,
        "assets": imported_assets,
    }


if __name__ == "__main__":
    # Example default path when synced via Export-GameAudioStems.ps1
    default_manifest = (
        r"G:\My Drive\Antigravity\Projects\Google Flow-music\exports"
        r"\game-audio\unreal\game-shadow-blade-dojo\adaptive_manifest.json"
    )
    if os.path.exists(default_manifest):
        result = import_flow_music_track(default_manifest)
        unreal.log(f"Flow Music UE5 import complete: {json.dumps(result)}")
    else:
        unreal.log_warning(f"Default manifest not present yet: {default_manifest}")
