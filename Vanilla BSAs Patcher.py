import os
import subprocess
import sys
import shutil
import winreg
import threading
import tempfile
import eel
import tkinter as tk
import blake3
from tkinter import filedialog
from concurrent.futures import ThreadPoolExecutor

ALL_BSAS = {
    "Fallout - Meshes.bsa": ("f7f2179ed7666e282d9308dfca614b134344cba7a033d94deb13cf5cc6be43c4", True),
    "Fallout - Misc.bsa": ("5a86184084145fd46feaefb8a8fc1c02caf4f9f004019cbbc1055b137d32d8ad", True),
    "Fallout - Textures.bsa": ("aec435835519438e467c3a97ed60fa8b0990a8446dfb5ce1ece35eedbe2d81ff", True),
    "Fallout - Textures2.bsa": ("90befeabbbb4dbb2188b78415bd86a548707405d29a4ab00e4a6644a9a7548e1", True),
    "Fallout - Sound.bsa": ("671f1ff31bbdcc4e00f04a922b69744f346567d9262e641ea7de1aebbab4dda5", True),
    "DeadMoney - Sounds.bsa": ("3f49992b3cfd1d85b76fe13319e852efc62508b2007b6dc26e1aff3615298801", False),
    "HonestHearts - Sounds.bsa": ("4bb535ecbd25f89ea1732d6fd802dba7ed2d1ba510e10a790854e7e6e330b8f3", False),
    "LonesomeRoad - Sounds.bsa": ("f0887cd205d2f34c1f67487fd09e9bbfe84afde56a8b6e467673047f03302830", False),
    "OldWorldBlues - Sounds.bsa": ("21cfe6f24a7bd692b34b86a40d871a9334acf673fbd83a6300905594cdbf0a10", False)
}

def log_to_ui(msg=""):
    eel.addLog(msg)

@eel.expose
def detect_data_path():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Bethesda Softworks\FalloutNV") as key:
            data_path = os.path.join(winreg.QueryValueEx(key, "Installed Path")[0], "Data")
            if os.path.isdir(data_path):
                return data_path
    except OSError as e:
        log_to_ui(f"Failed to auto-detect game installation path: {e}")
    return ""

@eel.expose
def select_folder():
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        folder = filedialog.askdirectory()
        root.destroy()
        return folder or ""
    except Exception as e:
        log_to_ui(f"Error opening file dialog: {e}")
        return ""

def convert_single_ogg(args):
    ogg_path, ffmpeg_exe, creation_flags, temp_dir = args

    # Skip same folders as FNV BSA Decompressor except for the Dog ones, which are already in WAV format
    skip_folders = {os.path.normpath(p) for p in ["sound/songs", "sound/fx/mus", "sound/fx/emt/raintoggle"]}
    
    rel_parts = os.path.normpath(os.path.relpath(ogg_path, temp_dir)).split(os.sep)
    if any(rel_parts[:len(sf.split(os.sep))] == sf.split(os.sep) for sf in skip_folders):
        return

    wav_path = os.path.splitext(ogg_path)[0] + ".wav"
    cmd = [ffmpeg_exe, "-y", "-i", ogg_path, "-acodec", "pcm_s16le", wav_path]
    if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags).returncode == 0:
        try: os.remove(ogg_path)
        except OSError as e: log_to_ui(f"Warning: Failed to remove original OGG file: {e}")

def convert_audio(temp_dir, current_dir):
    ffmpeg_exe = os.path.join(current_dir, "ffmpeg.exe")
    log_to_ui("Converting OGG files to WAV...")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    ogg_files = [(os.path.join(r, f), ffmpeg_exe, flags, temp_dir) for r, _, files in os.walk(temp_dir) for f in files if f.lower().endswith(".ogg")]
    with ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 1) - 1)) as executor:
        list(executor.map(convert_single_ogg, ogg_files))

def extract_mp3s(temp_dir, mp3_output_dir):
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.lower().endswith(".mp3"):
                src, dest = os.path.join(root, file), os.path.join(mp3_output_dir, os.path.relpath(root, temp_dir), file)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try: shutil.move(src, dest)
                except OSError as e: log_to_ui(f"Warning: Failed to move MP3 '{file}': {e}")

# Using BLAKE3 because it's fastest, even against SHA1
def calculate_blake3(file_path):
    hasher = blake3.blake3()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def process_bsas_thread(data_path, custom_path, options):
    current_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__)
    output_dir = custom_path or data_path
    is_game_folder = (output_dir == data_path)

    bsarch_exe = os.path.join(current_dir, "BSArch.exe")
    xdelta_exe = os.path.join(current_dir, "xdelta3.exe")
    ffmpeg_exe = os.path.join(current_dir, "ffmpeg.exe")
    vcdiff = os.path.join(current_dir, "Fallout - Misc.vcdiff")

    log_to_ui("Running prechecks...")
    for path, name in [(bsarch_exe, "BSArch.exe"), (xdelta_exe, "xdelta3.exe"), (ffmpeg_exe, "ffmpeg.exe"), (vcdiff, "Fallout - Misc.vcdiff")]:
        if not os.path.exists(path):
            log_to_ui(f"Error: {name} not found.")
            return eel.processFinished(False)

    if os.path.exists(os.path.join(data_path, "Fallout - Meshes2.bsa")):
        log_to_ui("Error: 'Fallout - Meshes2.bsa' found in Data. Remove it (output of older decompressor versions) and verify game files.")
        return eel.processFinished(False)

    try:
        os.makedirs(output_dir, exist_ok=True)
        if custom_path and any(f.lower() != "meta.ini" for f in os.listdir(output_dir)):
            log_to_ui("Error: Custom output directory must be empty (ignoring meta.ini).")
            return eel.processFinished(False)
    except OSError as e:
        log_to_ui(f"Error handling output directory: {e}")
        return eel.processFinished(False)

    try:
        total, _, free = shutil.disk_usage(output_dir)
        if free < 8 * 1024**3:
            log_to_ui(f"Error: Insufficient free disk space (required: 8GB, total: {total / (1024**3):.2f}GB, available: {free / (1024**3):.2f}GB).")
            return eel.processFinished(False)
    except OSError:
        log_to_ui(f"Warning: Could not check disk space: {e}")

    if os.path.normpath(output_dir).lower().startswith(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)").lower()):
        log_to_ui("Warning: The game is installed in 'Program Files (x86)'. UAC may restrict permissions.")

    log_to_ui("All prechecks passed.")
    log_to_ui()

    backup_dir = os.path.join(data_path, "Vanilla BSAs backup") if is_game_folder else None
    if backup_dir:
        try: os.makedirs(backup_dir, exist_ok=True)
        except OSError as e:
            log_to_ui(f"Error: Could not create backup directory: {e}")
            return eel.processFinished(False)

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    try:
        if options.get("verify_hashes"):
            log_to_ui("Verifying hashes...")
            active_bsas = []
            for bsa_name, (expected_hash, is_required) in ALL_BSAS.items():
                backup_path = os.path.join(backup_dir, bsa_name) if backup_dir else ""
                game_path = os.path.join(data_path, bsa_name)
                target = backup_path if (backup_dir and os.path.exists(backup_path)) else (game_path if os.path.exists(game_path) else "")

                if not target:
                    if is_required:
                        log_to_ui(f"Error: Required file '{bsa_name}' not found!")
                        return eel.processFinished(False)
                    log_to_ui(f"Warning: '{bsa_name}' not found, skipping.")
                    continue

                if calculate_blake3(target) != expected_hash:
                    log_to_ui(f"Error: Hash mismatch for '{bsa_name}'!")
                    log_to_ui()
                    log_to_ui("If your game language is set to English, verify the files. If it is in another language, disable the hash verification option above, as it is only a safety measure.")
                    return eel.processFinished(False)
                
                active_bsas.append(bsa_name)

            log_to_ui("Hashes verified.")
        else:
            log_to_ui("Hash verification skipped.")
            log_to_ui()
            active_bsas = []
            for bsa_name, (_, is_required) in ALL_BSAS.items():
                backup_path = os.path.join(backup_dir, bsa_name) if backup_dir else ""
                game_path = os.path.join(data_path, bsa_name)
                target = backup_path if (backup_dir and os.path.exists(backup_path)) else (game_path if os.path.exists(game_path) else "")

                if not target:
                    if is_required:
                        log_to_ui(f"Error: Required file '{bsa_name}' not found!")
                        return eel.processFinished(False)
                    log_to_ui(f"Warning: '{bsa_name}' not found, skipping.")
                    continue
                active_bsas.append(bsa_name)

        total = len(active_bsas)
        for idx, bsa_name in enumerate(active_bsas):
            eel.updateProgress(int((idx / total) * 100))
            log_to_ui(f"> Processing '{bsa_name}'...")

            bsa_path = os.path.join(data_path, bsa_name)
            backup_bsa_path = os.path.join(backup_dir, bsa_name) if backup_dir else ""

            if not os.path.exists(bsa_path) and backup_dir and os.path.exists(backup_bsa_path):
                bsa_path = backup_bsa_path

            if is_game_folder and os.path.dirname(bsa_path) != backup_dir:
                if os.path.exists(backup_bsa_path):
                    bsa_path = backup_bsa_path
                else:
                    log_to_ui("Backing up...")
                    try:
                        shutil.move(bsa_path, backup_bsa_path)
                        bsa_path = backup_bsa_path
                    except OSError as e:
                        log_to_ui(f"Error backing up: {e}")
                        return eel.processFinished(False)

            # Delta patch
            with tempfile.TemporaryDirectory() as temp_dir:
                if bsa_name.lower() == "fallout - misc.bsa" and os.path.exists(xdelta_exe):
                    log_to_ui("Applying delta patch....")
                    patched = os.path.join(temp_dir, "Fallout - Misc_patched.bsa")
                    cmd = [xdelta_exe, "-d", "-f", "-s", bsa_path, vcdiff, patched]
                    if subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags).returncode == 0:
                        bsa_path = patched
                    else:
                        log_to_ui("Error: xdelta failed.")
                        return eel.processFinished(False)

                log_to_ui("Unpacking...")
                if subprocess.run([bsarch_exe, "unpack", bsa_path, temp_dir, "-fnv"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags).returncode != 0:
                    log_to_ui("Error: Unpacking failed.")
                    return eel.processFinished(False)

                # Fix Misc archive
                if bsa_name.lower() == "fallout - misc.bsa":
                    bad_file = os.path.join(temp_dir, "menus", "s.txt")
                    if os.path.exists(bad_file):
                        try: os.remove(bad_file)
                        except OSError: pass

                    # Merge Meshes2 with Misc
                    meshes2_path = os.path.join(output_dir, "Fallout - Meshes2.bsa")
                    if os.path.exists(meshes2_path):
                        log_to_ui("Merging Meshes2 with Misc...")
                        if subprocess.run([bsarch_exe, "unpack", meshes2_path, temp_dir, "-fnv"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags).returncode == 0:
                            try: os.remove(meshes2_path)
                            except OSError: pass

                if options.get("split_mp3"):
                    extract_mp3s(temp_dir, output_dir)
                if options.get("ogg_to_wav"):
                    convert_audio(temp_dir, current_dir)

                log_to_ui("Repacking...")
                out_bsa = os.path.join(output_dir, bsa_name)
                if os.path.exists(out_bsa):
                    try: os.remove(out_bsa)
                    except OSError: pass

                pack_cmd = [bsarch_exe, "pack", temp_dir, out_bsa, "-fnv"]
                if not options.get("decompress"):
                    pack_cmd.append("-z")

                if subprocess.run(pack_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags).returncode != 0:
                    log_to_ui("Error: Packing failed.")
                    return eel.processFinished(False)
                log_to_ui(f"Done with '{bsa_name}'.")
                log_to_ui()

        eel.updateProgress(100)
        log_to_ui("Patching successful!")
        eel.processFinished(True)

    except Exception as e:
        log_to_ui(f"Error during execution: {e}")
        eel.processFinished(False)

@eel.expose
def start_processing(path, custom, options):
    threading.Thread(target=process_bsas_thread, args=(path, custom, options), daemon=True).start()

if __name__ == "__main__":
    eel.init("web")
    eel.start("index.html", size=(720, 680), mode='default')