# Refit Studio

Auto refit clothing for any V body mod in Cyberpunk 2077, female or male.
Nexus Mods page: https://www.nexusmods.com/cyberpunk2077/mods/37166

## Download

### [⬇ Download Refit Studio (latest version)](https://github.com/ANIMEFREG/RefitStudio/releases/latest/download/RefitStudio.zip)

1. Unpack the zip anywhere (a short path like `Documents\RefitStudio` is best)
2. Run `RefitStudio.exe`
3. If Windows says "Windows protected your PC", click **More info** and then **Run anyway**

You also need [Blender 4.2 or newer](https://www.blender.org/download/), the game and ArchiveXL. The launcher downloads WolvenKit CLI for you with one button. Full guide is in `README.txt` inside the zip.

Older versions are on the [Releases](https://github.com/ANIMEFREG/RefitStudio/releases) page.

## What is in this repository

- `src/` - the launcher (`RefitStudio.exe`), a single C# WinForms file.
- `core/` - Python scripts that run inside Blender (fitting, workshop panel, body profiles) and the `studio.blend` workshop scene.

The release archive on Nexus contains exactly these files plus the built `RefitStudio.exe` and readme files.

## Build from source

Requirements: Windows 10 or 11. No extra tools needed - it uses the C# compiler that ships with Windows (.NET Framework 4, `csc.exe`).

1. Open the `src` folder.
2. Run `build.bat`.
3. `RefitStudio.exe` is created in the repository root.

`core/` is plain Python source, nothing to build.

## Run

Put `RefitStudio.exe` next to the `core` folder and start it. You also need Blender 4.2+ and WolvenKit CLI (the launcher can download WolvenKit from its official GitHub releases).

## Versions

- **0.3.0** - this repository.
- **0.1.0** - the build submitted to Nexus Mods for file verification: https://github.com/ANIMEFREG/refit-studio-nexus-verification

## Changelog

### 0.3.0

- Male V. Pick Female V or Male V next to Bodies in the launcher
- Body profiles, the clothing list and tattoos follow the switch
- The workshop loads a lot faster
- A mod you opened before opens right away
- Items get ready in the background while you look at the list
- Waistbands, belt loops and pockets dont poke through each other after Auto fit anymore

### 0.2.1

- The item in the workshop keeps its UV maps, so you can export it from Blender with UVs

### 0.2.0

- One Export button for Item, Whole mod and Tattoos, to Vortex or as a zip
- Modders can save just the .mesh under their own name
- The mod list shows only clothing mods
- Clean mod names in the list
- Small + and − buttons to add or remove a clothing mod by hand
- New look for the launcher
- New look for the workshop with Fit, Sculpt and Export tabs
- Only the brushes you need in the workshop, Grab, Smooth and Inflate
- No extra gap between cloth and skin after Auto fit
- Bodies far from vanilla are followed more closely
- Sleeve ends and hems dont flare out anymore
- Cloth goes under the skin in fewer spots
