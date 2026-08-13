from pathlib import Path
import textwrap
from send2trash import send2trash
import re
import subprocess
import signal
import ffmpeg
import time
import tomllib
from functools import wraps

def load_config():
    with open("config.toml", "rb") as f:
        return tomllib.load(f)

def run_once(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not wrapper.has_run: # type: ignore
            wrapper.has_run = True # type: ignore
            return func(*args, **kwargs)
        # Optional: return a default value or print a message if skipped
        return None
    wrapper.has_run = False # type: ignore
    return wrapper

# Usage:
@run_once
def initialize_system():
    config = load_config()
    PathHelper.LogFile = Path(config["Media"]["LogFile"])
    PathHelper.StagingPath = Path(config["Media"]["Staging"])
    
    for entry in config["Media"]["Libraries"]:
        PathHelper.LibraryDirs[entry["name"]] = Path(entry["path"])

    for encodeInfo in config["Media"]["Encoding"]:
        base_path = Path(encodeInfo["Base"])

        for info in encodeInfo["DirPair"]:
            source = base_path / info["Source"]
            target = base_path / info["Target"]
            PathHelper.EncodingList.append([source, target])
            PathHelper.SourceDirs[target.name] = target

    # Crunchyroll Downloader info
    PathHelper.CRDL_Path = Path(config["Media"]["CRDL_Path"])
    PathHelper.CRDL_Target = Path(config["Media"]["CRDL_Target"])
    PathHelper.CRDL_exe = Path(config["Media"]["CRDL_exe"])
    PathHelper.CRDL_TokenName = Path(config["Media"]["CRDL_token"])
    PathHelper.CRDL_UpdateList = config["Media"]["CRDL_UpdateList"]
    PathHelper.CRDL_CompletedList = config["Media"]["CRDL_CompletedList"]

    DirManagerInfo = config["DirectoryManager"]
    DirectoryManager.MovieFile_Exts = DirManagerInfo["MovieFile_Exts"]
    DirectoryManager.AudioFile_Exts = DirManagerInfo["AudioFile_Exts"]
    DirectoryManager.Match_Exts     = DirManagerInfo["Match_Exts"]
    DirectoryManager.IgnoreDirs     = DirManagerInfo["IgnoreDirs"]
    DirectoryManager.CleanEpisodeNameList = DirManagerInfo["CleanEpisodeList"]

    print("System initialized!")


def IsvalidSubPath(target_path:Path, base_dir:Path):
    # .resolve() eliminates symlinks and standardizes "../" structures
    resolved_base = Path(base_dir).resolve()
    resolved_target = Path(target_path).resolve()
    
    return resolved_target.is_relative_to(resolved_base)

def flatten_elements(mixed_list):
    for item in mixed_list:
        if isinstance(item, list):
            yield from flatten_elements(item)  # Unpack the sublist items
        else:
            yield item       # Keep standalone strings intact

class CorruptException(Exception):
    """Raised when FFMPEG encounters a corrupted download"""
    pass

class PathHelper:
    # File to dump corrupted media found by ffmpeg
    LogFile = Path("")

    StagingPath = Path("")
    EncodingList = []
    SourceDirs = {}
    LibraryDirs = {}

    # Crunchroll Downloader info
    CRDL_Path = Path("")
    CRDL_Target = Path("")
    CRDL_exe = Path("")
    CRDL_TokenName = Path("")
    # Array of url lists and targeted audio streams
    CRDL_UpdateList = []
    CRDL_CompletedList = []

    def GetRelativeToSource(self, nestedPath:Path):
        for source_path in self.SourceDirs.values():
            if nestedPath.is_relative_to(source_path) and nestedPath != source_path:
                return nestedPath.relative_to(source_path)
    # End GetRelativeToSource

    def GetRelativeToLibrary(self, nestedPath:Path):
        for library_path in self.LibraryDirs.values():
            if nestedPath.is_relative_to(library_path) and nestedPath != library_path:
                return nestedPath.relative_to(library_path)
    # End GetRelativeToLibrary


    def GetSourceDir(self):
        while True:
            print("Available Sources:")
            enum_list = list(enumerate(self.SourceDirs.items()))
            for idx, item in enum_list:
                print(f"[{idx}] {item[0]}")

            try:
                user_input = int(input("Input Selection: "))
                if 0 <= user_input <= len(enum_list):
                    return enum_list[user_input][1][1]
                else:
                    print(f"Invalid range, please input 0<=>{len(enum_list) - 1}")

            except ValueError:
                print(f"Invalid input, please input [0,{len(enum_list) - 1}]")
    # End GetSourceDir

    def GetLibraryDir(self):
        while True:
            print("Available Sources:")
            enum_list = list(enumerate(self.LibraryDirs.items()))
            for idx, item in enum_list:
                print(f"[{idx}] {item[0]}")

            try:
                user_input = int(input("Input Selection: "))
                if 0 <= user_input <= len(enum_list):
                    return enum_list[user_input][1][1]
                else:
                    print(f"Invalid range, please input 0<=>{len(enum_list) - 1}")

            except ValueError:
                print(f"Invalid input, please input [0,{len(enum_list) - 1}]")
    # End GetLibraryDir

    def CleanupDirs(self):
        try:
            print("Cleaning Staging Path. . .")
            RemoveEmptyDirs(self.StagingPath)
        except:
            pass
        
        try:
            print("Cleaning CRDL Paths. . .")
            RemoveEmptyDirs(self.CRDL_Path)
            RemoveEmptyDirs(self.CRDL_Target)
        except:
            pass
        
        try:
            print("Cleaning Encoding Paths. . .")
            for dir_pair in self.EncodingList:
                RemoveEmptyDirs(dir_pair[0])
                RemoveEmptyDirs(dir_pair[1])
        except:
            pass
        
        try:
            print("Cleaning Library Paths. . .")
            for library_path in self.LibraryDirs.values():
                RemoveEmptyDirs(library_path)
        except:
            pass
    # End CleanupDirs
# End PathHelper

def RemoveEmptyDirs(targetPath:Path):
    if targetPath.is_dir():
        childDirs = list(targetPath.iterdir())
        for child in childDirs:
            RemoveEmptyDirs(child)
        if not any(targetPath.iterdir()):
            try:
                targetPath.rmdir()
            except:
                print(f"Could not remove: {targetPath}")

def ChoseSubDirectory(InitialPath:Path, canChooseInitial:bool = True):
    WorkingPath = InitialPath

    while True:
        subdirectories = [x for x in WorkingPath.iterdir() if x.is_dir()]
        subFiles = [x.name for x in WorkingPath.iterdir() if x.is_file()]
        subDirNames = [x.name for x in subdirectories]
        print()
        print("Available Directories:")
        print(*subDirNames, sep="\n", )
        print("Available Files:")
        print(*subFiles, sep="\n", )

        uInput = input("Select Dir: ")

        # Only allow parent access if still within the initial path
        if uInput == "..":
            if IsvalidSubPath(WorkingPath.parent, InitialPath):
                WorkingPath = WorkingPath.parent
                continue
            return None

        if not uInput:
            if WorkingPath == InitialPath and not canChooseInitial:
                continue
            return WorkingPath

        path = Path(uInput)
        if not path.is_absolute():
            path = WorkingPath / path

        # Check existence
        if path.exists() and IsvalidSubPath(path, InitialPath):
            
            # Optional: Distinguish between files and directories
            if path.is_file():
                WorkingPath = path.parent
            elif path.is_dir():
                WorkingPath = path
        else:
            select_subdir = [subdir for subdir in subdirectories if uInput.casefold() in subdir.name.casefold()]

            if len(select_subdir) > 1:
                print("Need more info. Matched Dirs:")
                dir_names = [d.name for d in select_subdir]
                print(dir_names)
            elif len(select_subdir) == 0:
                print("No matching directories, try again")
            else:
                print(f"Selected {select_subdir[0].name}")
                WorkingPath = select_subdir[0]
# End ChoseSubDirectory

def ExtractSeasonEpisodeNum(filename:str):
    # Regex breakdown:
    # [sS] matches 'S' or 's'
    # (\d+) captures one or more digits for the Season
    # [eE] matches 'E' or 'e'
    # (\d+) captures one or more digits for the Episode
    match = re.search(r'[sS](\d+)[eE](\d+)', filename)
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
        return season, episode, match
    return None, None, None

def GetVideoStreamArgs(VideoStream, StreamNumber:int):
    out_args = []
    if VideoStream["codec_name"] == "av1":
        out_args.extend([f"-c:v:{StreamNumber}", "copy"])
        return out_args
    
    presetVal = 4
    crfVal = 30
    height = int(VideoStream['height'])
    if height == 2200:
        crfVal = 38
    if height <= 1210:
        crfVal = 32
    if height <= 1000:
        crfVal = 26
    if height <= 481 :
        presetVal = 2
        crfVal = 22

    tune_args = [
        "tune=0",
        "scd=1",
        "enable-dlf=1",
        "enable-variance-boost=1",
        "keyint=10s"
    ]

    out_args.extend(["-c:v", "libsvtav1"])
    out_args.extend(["-crf", f"{crfVal}"])
    out_args.extend(["-preset", f"{presetVal}"])
    out_args.extend(["-pix_fmt", "yuv420p10le"])
    out_args.extend(["-svtav1-params", ":".join(tune_args)])

    return out_args
    

def GetAudioStreamArgs(AudioStream, StreamNumber:int):
    out_args = []
    
    if AudioStream["codec_name"] == "opus":
        out_args.extend([f"-c:a:{StreamNumber}", "copy"])
        return out_args

    out_args.extend([f"-c:a:{StreamNumber}", "libopus"])
    
    sampleRate = 60000
    parse_rate = int(AudioStream["sample_rate"])
    if parse_rate < sampleRate:
        sampleRate = parse_rate

    num_channels = int(AudioStream["channels"])
    target_bitrate = num_channels * sampleRate
    out_args.extend([f"-b:a:{StreamNumber}", f"{target_bitrate / 1000:.0f}K"])

    if num_channels == 1:
        # Mono
        out_args.extend([f"-filter:a:{StreamNumber}", "aformat=channel_layouts=mono"])

    elif num_channels == 2:
        # Stereo
        out_args.extend([f"-filter:a:{StreamNumber}", "aformat=channel_layouts=stereo"])

    elif num_channels == 6:
        # 5.1 Surround
        out_args.extend([f"-filter:a:{StreamNumber}", "channelmap=channel_layout=5.1(side),aformat=channel_layouts=5.1"])
        out_args.extend([f"-mapping_family:a:{StreamNumber}", "1"])

    elif num_channels == 8:
        # 7.1 Surround
        out_args.extend([f"-filter:a:{StreamNumber}", "aformat=channel_layouts=7.1"])
        out_args.extend([f"-mapping_family:a:{StreamNumber}", "1"])

    lang = AudioStream["tags"]["language"]
    out_args.extend([f"-metadata:s:a:{StreamNumber}", f"language={AudioStream["tags"]["language"]}"])

    fallbackTitle = ""
    if lang == "jpn":
        fallbackTitle = "Japanese"
    if lang == "eng":
        fallbackTitle = "English"

    out_args.extend([f"-metadata:s:a:{StreamNumber}", f"title={AudioStream["tags"].get("title", fallbackTitle)}"])


    return out_args

def GetFFMPEGArgs(mediaPath:Path):
    print(f"Getting encoding info for {mediaPath.parent.name}/{mediaPath.name}")
    # Probe the video file
    probe = ffmpeg.probe(mediaPath)

    detect_subtitles = False
    num_streams_audio = 0
    num_streams_video = 0
    media_args = []
    stream_map = []
    for stream in probe['streams']:

        if stream['codec_type'] == 'video':
            stream_map.extend(["-map", f"0:{stream["index"]}"])
            media_args.extend(GetVideoStreamArgs(stream, num_streams_video))
            num_streams_video += 1

        if stream['codec_type'] == 'audio':
            stream_map.extend(["-map", f"0:{stream["index"]}"])
            media_args.extend(GetAudioStreamArgs(stream, num_streams_audio))
            num_streams_audio += 1

        if stream['codec_type'] == 'subtitle' and not detect_subtitles:
            detect_subtitles = True
            stream_map.extend(["-map", "0:s"])
            media_args.extend(["-c:s", "copy"])

    media_args[:0] = stream_map
    return media_args

def parseFFMPEGOutput(process:subprocess.Popen):
    error_trigger1 = "error while decoding"     # The keyword that triggers the kill

    overwrite_trigger = "frame="

    if process.stdout:
        seg_out = False
        for line in process.stdout:
            end = ""
            if overwrite_trigger in line:
                seg_out = True
                end = "\r"
                line = line.replace("\n", "")
            elif seg_out:
                seg_out = False
                print()
            print(line, end=end, flush=True)  # Print the process output to your console
            
            # Check for the error message
            if error_trigger1 in line:
                raise CorruptException("Error: Corrupt decoded frame")
    else:
        raise Exception("process.stdout Not Found!")
    # End parseFFMPEGOutput

def ExecFFMPEG(sourceFile:Path, targetFile:Path):

    arguments = [
        "ffmpeg",
        "-i", str(sourceFile),
        "-map_metadata", "0",
    ]

    arguments.extend(GetFFMPEGArgs(sourceFile))

    arguments.append(str(targetFile))
        
    print()
    print("FFMPEG:")
    print(*arguments, " ")
    print()

    # Start the process with stdout and stderr captured
    process = subprocess.Popen(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Merge stderr into stdout to catch all errors
        text=True # Returns strings instead of bytes
    )

    safeFlag = False
    try:
        while process.poll() is None:
            parseFFMPEGOutput(process)
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Processing Interrupt, sending SIGKILL")
        process.kill()

    except CorruptException as e:
        process.kill()
        outfile = G_PathHelper.LogFile.with_stem(G_PathHelper.LogFile.stem + " - Corrupt Media")
        with open(outfile, mode="+a", encoding="utf-8") as f:
            target = G_PathHelper.GetRelativeToSource(sourceFile)
            f.write(f"Corrupt Frames {str(target)}\n")
        print("Corrupt Frames detected, Skipping file...")
        safeFlag = True

    except Exception as e:
        print(f"An exception occurred: {e}")
        process.kill()

    process.wait()
    print()
    parseFFMPEGOutput(process)
    print()
    pCode = process.returncode
    print(f"FFMPEG({pCode}) exited")

    if pCode:
        try:
            print(f"recycling {targetFile.parent.name}/{targetFile.name}")
            send2trash(targetFile)
        except FileNotFoundError:
            print("File failed to save, continuing")

    return pCode == 0 or safeFlag


def ExecAudioFFMPEG(sourceFile:Path, targetFile:Path):
    arguments = [
        "ffmpeg",
        "-i", str(sourceFile),
        "-q:a",
        "0",
        "-map_metadata",
        "0",
        "-id3v2_version",
        "3",
        str(targetFile)
    ]
    
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        result = subprocess.run(arguments)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    if result.returncode:
        send2trash(targetFile)

    return result.returncode == 0


def parseCRDLOutput(process:subprocess.Popen):
    result = True
    skip_list = [
        "is already downloaded, skipping...",
        "No season number specified"
    ]
    error_list = [
        "Too many requests",
        "TOO_MANY_ACTIVE_STREAMS"
    ]
    restart_list = [
        "Recovered from error"
    ]

    if process.stdout:
        seg_out = False
        season_mark = False
        for line in process.stdout:
            if any(sub in line for sub in skip_list):
                continue

            end = ""
            if "%" in line:
                seg_out = True
                end = "\r"
                line = line.replace("\n", "")
            elif seg_out:
                seg_out = False
                print()
            elif "Downloading season" in line:
                season_mark = True
            elif season_mark and line == "\n":
                season_mark = False
                continue
            print(line, end=end, flush=True)  # Print the process output to your console
            
            if any(sub in line for sub in restart_list):
                print(f"\n[ALERT] Error message found! Restarting CRDL {process.pid}...")
                process.kill()   # Forcefully terminate the process

            if any(sub in line for sub in error_list):
                print(f"\n[ALERT] Error message found! Killing process {process.pid}...")
                process.kill()   # Forcefully terminate the process
                result = False
    else:
        raise Exception("process.stdout Not Found!")
    
    return result


def RunCRDL(url_file:str, language:str):
    crdl_exe = G_PathHelper.CRDL_Path / G_PathHelper.CRDL_exe
    if not crdl_exe.exists():
        print(f"Error: {crdl_exe.name} does not exist!")
        return
    etp_rt_file = G_PathHelper.CRDL_Path / "cr-etp-rt.txt"
    if not etp_rt_file.exists():
        print(f"Error: {etp_rt_file.name} does not exist!")
        return

    etp_rt_token = etp_rt_file.read_text().strip()

    # Define the command
    command = [str(crdl_exe.resolve()), "--etp-rt", etp_rt_token, "--audio-lang", language, "--subs-lang", "en-US", "--file", url_file]

    result = True
    status = None
    runLoop = True
    while runLoop:
        # Start the process with stdout and stderr captured
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout to catch all errors
            text=True,                  # Returns strings instead of bytes
            cwd=G_PathHelper.CRDL_Path
        )
        print(f"Started process CRDL:{process.pid}. Monitoring output...")

        while process.poll() is None:
            # Read output line-by-line in real-time
            try:
                runLoop= result = parseCRDLOutput(process)
                time.sleep(0.1)

            except KeyboardInterrupt:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                runLoop = False
                result = False

            except Exception as e:
                print(f"An exception occurred: {e}")
                process.kill()
                runLoop = False
                result = False

        # Process Loop
        status = process.returncode
        if status == 0:
            print(f"CRDL Finished pulling {url_file}!")
            runLoop = False
            
        # Ensure the process resources are cleaned up
        print()
    # While runLoop

    print()
    print(f"Process finished with: {status}.")
    # end CRDL Loop


    RemoveEmptyDirs(G_PathHelper.CRDL_Path)
    return result
    # End RunCRDL

class DirectoryManager:
    MovieFile_Exts = []
    AudioFile_Exts = []
    Match_Exts = []
    IgnoreDirs = []
    CleanEpisodeNameList = []

    MetadataProviders = [
        {
            "Name" : "TVDB",
            "Tag" : "tvdbid"
        },
        {
            "Name" : "TheMovieDB",
            "Tag" : "tmdbid"
        },
        {
            "Name" : "IMDB",
            "Tag" : "imdbid"
        }
    ]

    def __init__(self, location:Path, libraryPath:Path, preScan:bool=False):
        if not location.exists():
            print(f"{location} Does not exist, Nothing to manage")
            raise FileNotFoundError
        if not location.is_dir():
            print(f"{location} Is not a directory")
            raise NotADirectoryError
        
        self.DirectoryPath = location
        self.LibraryPath = libraryPath
        self.EpisodeNum = 1
        self.SeasonNum = 1

        self.SetDirectoryFiles()
        if preScan:
            print("Scanning movie Files. . .")
            failure_list = []
            totalFiles = len(self.MovieFiles)
            scanned = 0
            for movie in self.MovieFiles:
                try:
                    ffmpeg.probe(movie)
                    scanned += 1
                    if scanned % 10 == 0:
                        print(f"Scanning {scanned} of {totalFiles}", end="\r", flush=True)
                except KeyboardInterrupt as e:
                    raise e
                except:
                    failure_list.append(str(movie))
            print()
            print("Scanning Audio Files. . .")
            totalFiles = len(self.AudioFiles)
            scanned = 0
            for audio in self.AudioFiles:
                try:
                    ffmpeg.probe(audio)
                    scanned += 1
                    if scanned % 10 == 0:
                        print(f"Scanning {scanned} of {totalFiles}", end="\r", flush=True)
                except KeyboardInterrupt as e:
                    raise e
                except:
                    failure_list.append(str(audio))

            print()
            if len(failure_list):
                print()
                print()
                print("ERROR - These files need fixing:")
                print(*failure_list, "\n")
                raise Exception("Cannot process files in folder")
    # End __init__

    def __del__(self):
        print(f"Cleaning Directory Path: {self.DirectoryPath}")
        child_paths = list(self.DirectoryPath.iterdir())
        for child_path in child_paths:
            try:
                RemoveEmptyDirs(child_path)
            except:
                pass
        
    def SetDirectoryFiles(self):
        print()
        print(f"{self.DirectoryPath.name} Contains")
        # Gather all files
        fileList = sorted([p for p in self.DirectoryPath.rglob("*") if p.is_file()])
        # filter Files by type
        print(f"Files Found: {len(fileList)}")
        self.AudioFiles = [f for f in fileList if f.suffix in self.AudioFile_Exts]
        print(f"Audio Found: {len(self.AudioFiles)}")
        self.MovieFiles = [f for f in fileList if f.suffix in self.MovieFile_Exts]
        print(f"Movies Found: {len(self.MovieFiles)}")
        print()
    # End SetDirectoryFiles


    def CleanEpisodeTitles(self):
        for movie in self.MovieFiles:
            name_stem = movie.stem
            for rep_string in self.CleanEpisodeNameList:
                f_string = rep_string[0]
                r_string = rep_string[1]
                if f_string in name_stem:
                    name_stem = name_stem.replace(f_string, r_string)
            movie.rename(movie.with_stem(name_stem))
        
        self.SetDirectoryFiles()

        print("Movie Files:")
        for movie in self.MovieFiles:
            print(f"{movie.stem}")

    def SendCRDLToRaw(self):
        for movie in self.MovieFiles:
            fileSize = movie.stat().st_size
            if fileSize == 0:
                continue
            print(f"Moving {movie.stem}")
            targetDir = G_PathHelper.CRDL_Target / movie.parent.name
            targetDir.mkdir(parents=True, exist_ok=True)
            newMovieFile = movie.copy_into(targetDir)
            if newMovieFile.exists():
                with open(movie, "w") as f:
                    pass
    # End SendCRDLToRaw

    def EditMovieSeriesInfo(self) -> bool:
        SeasonNum = 1
        EpisodeNum = 1
        seriesTitle = self.DirectoryPath.name
        skipCount = 0
        Finish = False

        for Movie in self.MovieFiles:
            # Check if the file is a .webm file
            if skipCount > 0:
                skipCount -= 1
                continue

            # Setup new file values
            skip = False
            partNum = 0
            partName = ""
            EpisodeName = ""

            # Construct the full file paths
            episode_stem = Movie.stem

            _, _, match = ExtractSeasonEpisodeNum(episode_stem)
            if match:
                if len(episode_stem) > match.end() + 2:
                    EpisodeName = episode_stem[match.end():]
        
            while True:
                res1 = None
                res2 = ""
                # Build the name of the output
                if partNum > 0:
                    partName = f"-part-{partNum}"

                episode_stem = f"{seriesTitle} S{SeasonNum:02d}E{EpisodeNum:02d}{EpisodeName}{partName}"
                
                print(textwrap.dedent(f"""
                Old Name: {Movie.stem}
                New Name: {episode_stem}\
                """))

                # if finish flag, the rest of the titles will be put into same season
                if Finish:
                    break

                # Process Input for name modifications
                user_res = input(textwrap.dedent("""\
                s - Season #
                e - Episode #
                p - Part #
                x - Skip #
                n - Name <name>
                f - Finish (auto increment episodes)
                q - quit early
                Correct?
                """)).split(maxsplit=1)

                if user_res:
                    res1 = user_res[0]

                if len(user_res) > 1:
                    res2: str = user_res[1]

                # Season #
                if res1 == "s":
                    if len(user_res) > 1:
                        SeasonNum = int(res2)
                    else:
                        SeasonNum += 1
                    EpisodeNum = 1

                # Episode #
                elif res1 == "e":
                    if len(user_res) > 1:
                        EpisodeNum = int(res2)
                    else:
                        EpisodeNum += 1

                # Part #
                elif res1 == "p":
                    if len(user_res) > 1:
                        partNum = int(res2)
                    else:
                        partNum += 1

                # Episode <name>
                elif res1 == "n":
                    EpisodeName = " " + res2

                # Skip #
                elif res1 == "x":
                    skip = True
                    if len(user_res) > 1:
                        skipCount = int(res2)-1
                    break

                # Finish in current season
                elif res1 == "f":
                    Finish = True

                # Done    
                elif not res1 or res1 == "y":
                    break

                # Quit
                elif res1 == "q":
                    return False
                
                else:
                    print("Unrecognized User input!\n")
            #end Naming Loop                    

            if skip:
                print(f"Skipping: {Movie.stem}")
            else:
                # Rename the file
                Movie.rename(Movie.with_stem(episode_stem))

                #check matching file
                for match_ext in self.Match_Exts:
                    match = Movie.with_suffix(match_ext)
                    if match.exists():
                        match.rename(match.with_stem(episode_stem))
                
                if partNum == 0:
                    EpisodeNum += 1
        # End Movie Loop

        print("End of files!")
        self.SetDirectoryFiles()
        return True
    # End EditMovieSeriesInfo

    def SortEpisodesIntoSeasons(self):
        for movie in self.MovieFiles:
            matches = [name for name in movie.parents if name in self.IgnoreDirs]
            if matches:
                print(f"Skipping due to matches: {matches}")
                continue
            s, e, _ = ExtractSeasonEpisodeNum(movie.stem)
            if s == None:
                print(f"{movie.name} Needs manual placement")
                continue
            print(f"File: {movie.stem} -> Season: {s}, Episode: {e}")
            seasonPath = self.DirectoryPath / f"Season {s:02d}"
            seasonPath.mkdir(parents=True, exist_ok=True)
            dest_path = seasonPath / movie.name
            if dest_path != movie:
                movie.rename(dest_path)
                #check matching file
                for match_ext in self.Match_Exts:
                    match = movie.with_suffix(match_ext)
                    if match.exists():
                        match.rename(dest_path.with_suffix(match_ext))
                
        self.SetDirectoryFiles()
    # End SortEpisodesIntoSeasons

    def AskForMetadataID(self):
        while True:
            print()
            for index, meta_provider in enumerate(self.MetadataProviders):
                print(f"[{index}] : {meta_provider["Name"]}")
            user_input = input("Input Metadata reference <index> <ID>: ").split()

            if not user_input:
                break

            try:
                if len(user_input) == 1:
                    if user_input[0] == "q":
                        break
                if len(user_input) == 2:
                    meta_supplier = self.MetadataProviders[int(user_input[0])]
                    directory_name = f"{self.DirectoryPath.name} [{meta_supplier["Tag"]}-{user_input[1]}]"
                    self.DirectoryPath = self.DirectoryPath.rename(self.DirectoryPath.with_name(directory_name))
                    break
                else:
                    raise IndexError(f"Incorrect user input: {user_input}")
            except:
                print(f"Invalid input: {user_input}")


    def EncodeDirectory(self, EncodePath:Path) -> bool:
        res = True
        if len(self.MovieFiles) > 0:
            for movie in self.MovieFiles:
                relativePath = movie.parent.relative_to(self.LibraryPath)
                targetPath = EncodePath / relativePath
                targetPath.mkdir(parents=True, exist_ok=True)
                targetFile = targetPath / movie.with_suffix(".mkv").name
                #check matching files
                for match_ext in self.Match_Exts:
                    match = movie.with_suffix(match_ext)
                    if match.exists():
                        match_target = targetPath / match.name
                        if not match_target.exists():
                            match.copy_into(targetPath)
                if not targetFile.exists():
                    res = ExecFFMPEG(sourceFile=movie, targetFile=targetFile)
                    if not res:
                        print(f"Encoding {movie.name} encountered an error. Stopping Encoding loop")
                        break
                
        
        if len(self.AudioFiles) > 0:
            for audio in self.AudioFiles:
                relativePath = audio.parent.relative_to(self.LibraryPath)
                targetPath = EncodePath / relativePath
                targetPath.mkdir(parents=True, exist_ok=True)
                targetFile = targetPath / audio.with_suffix(".mp3").name
                if not targetFile.exists():
                    res = ExecAudioFFMPEG(sourceFile=audio, targetFile=targetFile)
                    if not res:
                        break
        print(f"Finished encoding {self.DirectoryPath.name} ({res})")
        return res
    # End EncodeDirectory

# End DirectoryManager
G_PathHelper = PathHelper()

def main():
    initialize_system()
    global G_PathHelper
    
    while True:
        userInput = input(textwrap.dedent("""
            Choose Option:
            [1] Encoding (FFMPEG Video:AV1-SVT Audio:mp3)
            [2] Processing (Copy Dir to Staging, Rename Series)
            [3] Edit Staged Directory
            [4] Finalize (Copy from Staging folder to Library)
            [8] Run Crunchyroll Downloader
            [9] Move CRDL to Encoding
            [q] quit - Default
            """))
        
        if not userInput or userInput == "q":
            break

        if userInput == "1":
            use_list = []
            for encode_tuple in G_PathHelper.EncodingList:
                user_input = input(f"Process {encode_tuple[0]}? (Y/n)")
                if not user_input or user_input == "y":
                    use_list.append(encode_tuple)
            encode_list = []
            user_input = input(f"Pre-Scan Folders for ffmpeg issues? (N/y)")
            preScan = False
            if user_input == "y":
                preScan = True
            for entry in use_list:
                encode_list.append([DirectoryManager(entry[0], entry[0], preScan=preScan), entry[1]])
            for encode_pair in encode_list:
                if not encode_pair[0].EncodeDirectory(encode_pair[1]):
                    print("Halting Encoding process")
                    break
            

        if userInput == "2":
            # [2] Processing (Copy Dir to Process, rename series)
            starting_dir = G_PathHelper.GetSourceDir()
            source_path = ChoseSubDirectory(starting_dir, False)
            if source_path:
                relative_path = G_PathHelper.GetRelativeToSource(source_path)
                if relative_path:
                    print("Copying. . .")
                    G_PathHelper.StagingPath.mkdir(parents=True, exist_ok=True)
                    copied_path:Path = source_path.copy_into(G_PathHelper.StagingPath)
                    userInput = input(f"Do you wish to rename {copied_path.name} (Enter new name, or press enter)? ")
                    if userInput:
                        copied_path = copied_path.rename(copied_path.with_name(userInput))
                    dirManager = DirectoryManager(copied_path, G_PathHelper.StagingPath)
                    user_input = input("Clean Episode Titles (y)?")
                    if user_input == "y":
                        dirManager.CleanEpisodeTitles()
                    if dirManager.EditMovieSeriesInfo():
                        dirManager.SortEpisodesIntoSeasons()
                        dirManager.AskForMetadataID()


        if userInput == "3":
            # [2] Processing (Copy Dir to Process, rename series)
            staged_path = ChoseSubDirectory(G_PathHelper.StagingPath)
            if staged_path:
                dirManager = DirectoryManager(staged_path, G_PathHelper.StagingPath)
                user_input = input("Clean Episode Titles (y)?")
                if user_input == "y":
                    dirManager.CleanEpisodeTitles()
                if dirManager.EditMovieSeriesInfo():
                    dirManager.SortEpisodesIntoSeasons()
                    dirManager.AskForMetadataID()

        if userInput == "4":
            # [3] Finalizing (Copy Processed folder to Library)
            staged_path = ChoseSubDirectory(G_PathHelper.StagingPath, False)
            if staged_path:
                library_path = G_PathHelper.GetLibraryDir()
                print("Copying. . .")
                copied_path = staged_path.copy_into(library_path)

        if userInput == "8":
            url_order = [
                ["urls_u.txt", "ja-JP,en-US"],
                ["jp-urls_u.txt", "ja-JP"],
                ["urls.txt", "ja-JP,en-US"],
                ["jp-urls.txt", "ja-JP"]
            ]
            userInput = input(textwrap.dedent("""
                Choose Option:
                [1] Update
                [2] Completed
                [3] Both (Update -> Complete)
                """))
            res = True
            if userInput == "1" or userInput == "3":
                crdl_pair = url_order[0]
                res = RunCRDL(crdl_pair[0], crdl_pair[1])
                if res:
                    crdl_pair = url_order[1]
                    res = RunCRDL(crdl_pair[0], crdl_pair[1])

            if userInput == "2" or userInput == "3":
                crdl_pair = url_order[2]
                if res:
                    res = RunCRDL(crdl_pair[0], crdl_pair[1])
                crdl_pair = url_order[3]
                if res:
                    res = RunCRDL(crdl_pair[0], crdl_pair[1])
            print()
            print("finished CRDL")
            if res:
                userInput = "9"
            
        if userInput == "9":
            crdl_manager = DirectoryManager(G_PathHelper.CRDL_Path, G_PathHelper.CRDL_Path)
            crdl_manager.SendCRDLToRaw()

        print()
    # End User Input

    print("Closing JellyManager")
    G_PathHelper.CleanupDirs()

if __name__ == "__main__":
    main()
