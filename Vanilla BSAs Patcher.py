import os
import subprocess
import sys
import shutil
import winreg
import threading
import tempfile
import eel
import tkinter as tk
from tkinter import filedialog
from concurrent.futures import ThreadPoolExecutor

BSA_LIST = [
    "Fallout - Meshes.bsa",
    "Fallout - Misc.bsa",
    "Fallout - Textures.bsa",
    "Fallout - Textures2.bsa",
    "Fallout - Sound.bsa",
    "DeadMoney - Sounds.bsa",
    "HonestHearts - Sounds.bsa",
    "LonesomeRoad - Sounds.bsa",
    "OldWorldBlues - Sounds.bsa"
]

def log_to_ui(msg):
    eel.addLog(msg)

@eel.expose
def detect_data_path():
    try:
        reg_path = r"SOFTWARE\WOW6432Node\Bethesda Softworks\FalloutNV"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
            game_path, _ = winreg.QueryValueEx(key, "Installed Path")
            data_path = os.path.join(game_path, "Data")
            if os.path.isdir(data_path):
                return data_path
    except OSError as e:
        log_to_ui(f"Failed to auto-detect game installation path from registry: {e}")
    return ""

@eel.expose
def select_folder():
    try:
        root = tk.Tk()
        root.withdraw()  # Hide the main Tkinter window
        root.wm_attributes("-topmost", True)  # Bring the dialog to the front
        
        folder_selected = filedialog.askdirectory()
        root.destroy()  # Clean up the hidden window instance
        
        return folder_selected if folder_selected else ""
    except Exception as e:
        log_to_ui(f"Error opening folder picker dialog: {e}")
        return ""

def convert_single_ogg(args):
    ogg_path, ffmpeg_exe, creation_flags = args
    wav_path = os.path.splitext(ogg_path)[0] + ".wav"
    cmd = [ffmpeg_exe, "-y", "-i", ogg_path, "-acodec", "pcm_s16le", wav_path]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags)
    if result.returncode == 0:
        try:
            os.remove(ogg_path)
        except OSError as e:
            log_to_ui(f"Warning: Failed to remove original OGG file '{ogg_path}': {e}")

def convert_audio(temp_dir, current_dir):
    ffmpeg_exe = os.path.join(current_dir, "ffmpeg.exe")
    if not os.path.exists(ffmpeg_exe):
        log_to_ui("Warning: ffmpeg.exe not found. Make sure you extracted everything from the downloaded archive. Skipping OGG to WAV conversion.")
        return
    
    log_to_ui("Converting OGG files to WAV...")
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    ogg_files = []
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.lower().endswith(".ogg"):
                ogg_files.append((os.path.join(root, file), ffmpeg_exe, creation_flags))

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        list(executor.map(convert_single_ogg, ogg_files))

def extract_mp3s(temp_dir, mp3_output_dir):
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.lower().endswith(".mp3"):
                src_path = os.path.join(root, file)
                rel_path = os.path.relpath(src_path, temp_dir)
                dest_path = os.path.join(mp3_output_dir, rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                try:
                    shutil.move(src_path, dest_path)
                except OSError as e:
                    log_to_ui(f"Warning: Failed to extract MP3 file '{file}': {e}")

def process_bsas_thread(data_path, custom_path, options):
    if getattr(sys, 'frozen', False):
        current_dir = os.path.dirname(sys.executable)
    else:
        current_dir = os.path.dirname(os.path.abspath(__file__))

    output_dir = custom_path if custom_path else data_path
    is_game_folder = (output_dir == data_path)

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        log_to_ui(f"Error: Could not create output directory '{output_dir}': {e}")
        eel.processFinished(False)
        return

    # Prechecks
    log_to_ui("Running prechecks...")

    # Free space
    REQUIRED_STORAGE_BYTES = 8 * 1024 * 1024 * 1024
    try:
        total, _, free = shutil.disk_usage(output_dir)
        free_gb = free / (1024 ** 3) # Convert to GB
        if free < REQUIRED_STORAGE_BYTES:
            log_to_ui(f"Error: Insufficient free disk space. Required: 8GB, available: {free_gb:.3f}GB.")
            eel.processFinished(False)
            return
    except OSError as e:
        log_to_ui(f"Warning: Could not check for free disk space: {e}")

    # Program Files x86
    norm_output = os.path.normpath(output_dir).lower()
    pf_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)").lower()

    if norm_output.startswith(pf_x86):
        log_to_ui("Warning: Game directory is located in 'Program Files (x86)'. Windows UAC may cause permission issues, but the patcher will continue.")

    log_to_ui("Prechecks completed.\n")

    # Processing
    backup_dir = None
    if is_game_folder:
        backup_dir = os.path.join(data_path, "Vanilla BSAs backup")
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except OSError as e:
            log_to_ui(f"Error: Could not create backup directory '{backup_dir}': {e}")
            eel.processFinished(False)
            return

    bsarch_exe = os.path.join(current_dir, "BSArch.exe")
    xdelta_exe = os.path.join(current_dir, "xdelta3.exe")

    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    if not os.path.exists(bsarch_exe):
        log_to_ui("Error: BSArch.exe not found. Make sure you extracted everything from the downloaded archive.")
        eel.processFinished(False)
        return

    try:
        total = len(BSA_LIST)
        for idx, bsa_name in enumerate(BSA_LIST):
            eel.updateProgress(int(((idx) / total) * 100))
            log_to_ui(f"\nProcessing: {bsa_name}")

            bsa_path = os.path.join(data_path, bsa_name)
            if not os.path.exists(bsa_path) and backup_dir:
                bsa_path = os.path.join(backup_dir, bsa_name)

            if not os.path.exists(bsa_path):
                log_to_ui(f"Could not find '{bsa_name}'. Skipping.")
                continue

            if is_game_folder and os.path.dirname(bsa_path) != backup_dir:
                backup_bsa_path = os.path.join(backup_dir, bsa_name)
                log_to_ui("Backing up BSA...")
                try:
                    shutil.move(bsa_path, backup_bsa_path)
                    bsa_path = backup_bsa_path
                except OSError as e:
                    log_to_ui(f"Error: Failed to backup '{bsa_name}': {e}")
                    eel.processFinished(False)
                    return

            with tempfile.TemporaryDirectory() as temp_dir:

                temp_patched_bsa = None
                if bsa_name.lower() == "fallout - misc.bsa" and os.path.exists(xdelta_exe):
                    patch_path = os.path.join(current_dir, "Fallout - Misc.vcdiff")
                    if os.path.exists(patch_path):
                        log_to_ui("Delta patching Fallout - Misc.bsa...")
                        temp_patched_bsa = os.path.join(temp_dir, "Fallout - Misc_patched.bsa")
                        xdelta_cmd = [xdelta_exe, "-d", "-f", "-s", bsa_path, patch_path, temp_patched_bsa]
                        res = subprocess.run(xdelta_cmd, capture_output=True, text=True, creationflags=creation_flags)
                        if res.returncode == 0:
                            bsa_path = temp_patched_bsa
                        else:
                            log_to_ui(f"xdelta error: {res.stderr.strip()}")

                log_to_ui("Unpacking archive...")
                unpack_cmd = [bsarch_exe, "unpack", bsa_path, temp_dir]
                res_unpack = subprocess.run(unpack_cmd, capture_output=True, text=True, creationflags=creation_flags)

                if res_unpack.returncode != 0:
                    # log_to_ui(f"Unpacking failed: {res_unpack.stderr.strip()}") # Doesn't pass the error, not sure why
                    log_to_ui(f"Unpacking failed.")
                    continue

                # Remove broken file
                if bsa_name.lower() == "fallout - misc.bsa":
                    bad_file = os.path.join(temp_dir, "menus", "s.txt")
                    if os.path.exists(bad_file):
                        try:
                            os.remove(bad_file)
                            log_to_ui("Removed broken 'menus/s.txt'.")
                        except OSError as e:
                            log_to_ui(f"Warning: Could not remove broken 'menus/s.txt': {e}")

                    meshes2_path = os.path.join(output_dir, "Fallout - Meshes2.bsa")
                    if os.path.exists(meshes2_path):
                        log_to_ui("Merging Meshes2 BSA with Misc BSA...")
                        unpack_cmd2 = [bsarch_exe, "unpack", meshes2_path, temp_dir]
                        res2 = subprocess.run(unpack_cmd2, capture_output=True, text=True, creationflags=creation_flags)
                        if res2.returncode == 0:
                            try:
                                os.remove(meshes2_path)
                            except OSError as e:
                                log_to_ui(f"Warning: Could not remove 'Fallout - Meshes2.bsa' after merging: {e}")

                if options.get("split_mp3"):
                    extract_mp3s(temp_dir, output_dir)

                if options.get("ogg_to_wav"):
                    convert_audio(temp_dir, current_dir)

                output_bsa_path = os.path.join(output_dir, bsa_name)
                log_to_ui(f"Repacking: {output_bsa_path}")
                
                if os.path.exists(output_bsa_path):
                    try:
                        os.remove(output_bsa_path)
                    except OSError as e:
                        log_to_ui(f"Warning: Could not remove existing BSA before repacking: {e}")

                pack_cmd = [bsarch_exe, "pack", temp_dir, output_bsa_path, "-fnv"]
                if not options.get("decompress"):
                    pack_cmd.append("-z")

                res_pack = subprocess.run(pack_cmd, capture_output=True, text=True, creationflags=creation_flags)
                if res_pack.returncode != 0:
                    # log_to_ui(f"Packing failed: {res_unpack.stderr.strip()}") # Doesn't pass the error, not sure why
                    log_to_ui(f"Packing failed.")
                else:
                    log_to_ui(f"Done with {bsa_name}.")

        eel.updateProgress(100)
        log_to_ui("\nPatching successful!")
        eel.processFinished(True)

    except Exception as e:
        log_to_ui(f"Error during execution: {e}")
        eel.processFinished(False)

@eel.expose
def start_processing(data_path, custom_path, options):
    threading.Thread(target=process_bsas_thread, args=(data_path, custom_path, options), daemon=True).start()

if __name__ == "__main__":
    eel.init("web")
    eel.start("index.html", size=(720, 680), mode='default')