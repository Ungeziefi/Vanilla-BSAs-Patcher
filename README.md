Nexus Mods page [here](https://www.nexusmods.com/games/newvegas/mods/98738).

**Building**
- [Python](https://www.python.org/)
- [Eel](https://github.com/python-eel/Eel)
- [PyInstaller](https://pyinstaller.org/en/stable/)

And these next to the .py:
- [xdelta](https://github.com/jmacd/xdelta)
- [BSArch](https://www.nexusmods.com/newvegas/mods/64745)
- [ffmpeg](https://ffmpeg.org/)
- Fallout - Misc.vcdiff

To build: `python -m PyInstaller --onefile --windowed --icon=web/icon.ico --add-data "web;web" "Vanilla BSAs Patcher.py"`