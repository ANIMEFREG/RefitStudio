# Refit Studio

Auto refit clothing for any female V body mod in Cyberpunk 2077.
Nexus Mods page: https://www.nexusmods.com/cyberpunk2077/mods/37166

## What is in this repository

- `src/` - the launcher (`RefitStudio.exe`), a single C# WinForms file.
- `core/` - Python scripts that run inside Blender (fitting, workshop panel, body profiles) and the `studio.blend` workshop scene.

The release archive on Nexus contains exactly these files plus the built `RefitStudio.exe` and readme files.

## Build the launcher

Requirements: Windows 10 or 11. No extra tools needed - it uses the C# compiler that ships with Windows (.NET Framework 4, `csc.exe`).

1. Open the `src` folder.
2. Run `build.bat`.
3. `RefitStudio.exe` is created in the repository root.

`core/` is plain Python source, nothing to build.

## Run

Put `RefitStudio.exe` next to the `core` folder and start it. You also need Blender 4.2+ and WolvenKit CLI (the launcher can download WolvenKit from its official GitHub releases).

## Versions

- **0.2.0** - this repository.
- **0.1.0** - the build submitted to Nexus Mods for file verification: https://github.com/ANIMEFREG/refit-studio-nexus-verification

## Changes in 0.2.0

New features
- Export: one "Export…" button with a popup (Item / Whole mod / Tattoos, Vortex or zip).
- For modders: save just the `.mesh` under your own name.
- Clothing mod list shows only clothing mods ("Show all mods" to see the rest).
- Small "+" / "−" buttons add a clothing mod by hand (folder or .archive) or remove it from the list.

Look and comfort
- Clean mod names in the list (no versions or Vortex suffixes).
- New workshop: own header, tabs Fit / Sculpt / Export, only the brushes you need (Grab, Smooth, Inflate), tips before sculpting, cyberpunk style.
- New launcher in the same cyberpunk glass style.

Auto fit
- No extra gap between cloth and skin.
- Bodies very different from vanilla (big chest, wide hips) are followed more accurately.
- Sleeve ends and hems no longer flare out.
- Fewer spots where cloth goes under the skin.
- Checked against 170+ refits made by hand by body and clothing authors.
