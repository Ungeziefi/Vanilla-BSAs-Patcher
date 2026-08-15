Nexus Mods page [here](https://www.nexusmods.com/games/newvegas/mods/98738).

**Building**

```sh
uv sync
uv run pyinstaller --onefile --windowed --icon=web/icon.ico --add-data "web;web" "Vanilla BSAs Patcher.py"
```

---

**Usage**  
Next to the `.py` or the `.exe`:
- [BSArch](https://www.nexusmods.com/newvegas/mods/64745)
- Fallout - Misc.vcdiff
- libvorbis.dll
- libvorbisfile.dll
