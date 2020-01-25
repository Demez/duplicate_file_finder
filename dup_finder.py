import os
import sys
import hashlib
import datetime
from enum import Enum, auto
from threading import Thread

try:
    from send2trash import send2trash
except ImportError:
    print("WARNING: send2trash module not installed, "
          "files will be deleted instead of moved to the recycle bin")

# ideas
#  - test by similarity amount


# Specify how many bytes of the file you want to open at a time
BLOCKSIZE = 65536


class FileMarks(Enum):
    MASTER = auto(),
    LINK = auto(),
    DELETE = auto(),  # moves to recycle bin on windows, linux, idk, trash?
    IGNORE = auto(),


class File:
    def __init__(self, file_path: str, file_mark: Enum = FileMarks.IGNORE):
        self.path = file_path
        self.link = os.path.islink(file_path)
        if file_mark not in FileMarks:
            raise Exception("File mark not in FileMarks Enum class: " + str(file_mark))
        self._mark = file_mark
        
    # could pick a better name
    def set_mark(self, mark: Enum) -> None:
        if mark in FileMarks:
            self._mark = mark
        
    def get_mark(self) -> Enum:
        return self._mark


class DuplicateFinder:
    def __init__(self):
        self.search_directory_list = []
        self.exclude_directory_list = []
        self.exclude_ext_list = []
        self.ext_list = []
        self.duplicate_files = []
        self.found_file_list = []
        self.file_size_dict = {}
        self.file_hash_dict = {}
        self.total_file_count = 0
        self._files_scanned = 0
        self.total_size = 0
        self.space_saved = 0
        self.new_size = 0
        self.ignore_links = True
        self.use_oldest_mod_date = True

        self.found_file_objs = {}
        # self.master_file_dict = {}  # key is master file, value is list of sys links
        
        self._file_scanned_callback = None
        self._dup_found_callback = None
        self._scan_finished_callback = None
        self._apply_callback = None
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    def set_file_scanned_callback(self, callback: classmethod) -> None:
        self._file_scanned_callback = callback

    def set_dup_found_callback(self, callback: classmethod) -> None:
        self._dup_found_callback = callback

    def set_scan_finished_callback(self, callback: classmethod) -> None:
        self._scan_finished_callback = callback

    def set_apply_callback(self, callback: classmethod) -> None:
        self._apply_callback = callback

    def _run_file_scanned_callback(self) -> None:
        # self._files_scanned += 1
        new_file_count = len(self.found_file_list)
        if self._files_scanned == new_file_count:
            return
        self._files_scanned = new_file_count
        # print("Files scanned: " + str(self._files_scanned))
        if self._file_scanned_callback is not None:
            self._file_scanned_callback(self._files_scanned)

    def _run_dup_found_callback(self, dup_file_list: list) -> None:
        if self._dup_found_callback is not None:
            self._dup_found_callback(dup_file_list)

    def _run_scan_finished_callback(self) -> None:
        if self._scan_finished_callback is not None:
            self._scan_finished_callback()

    def _run_apply_callback(self, file_obj: File, dup_list: list) -> None:
        if self._apply_callback is not None:
            self._apply_callback(file_obj, dup_list)

    def get_duplicate_file_count(self) -> int:
        total_dup_files = 0
        for dup_list in self.duplicate_files:
            total_dup_files += len(dup_list)
        return total_dup_files

    def update_size_estimates(self):
        self.total_size = 0
        self.new_size = 0
        self.space_saved = 0
        
        for dup_list in self.duplicate_files:
            start_file_size = self._get_file_size(dup_list[0])
            self.new_size += start_file_size
            list_size = 0
            for file_path in dup_list:
                file_size = self._get_file_size(file_path)
                list_size += file_size
            self.total_size += list_size
            self.space_saved += (list_size - start_file_size)
            
    @staticmethod
    def _get_oldest_mod_time(dup_list: list) -> float:
        time_list = []
        for file_path in dup_list:
            date_modified = get_date_modified(file_path)
            if date_modified != -1.0:
                time_list.append(date_modified)
        return min(time_list)

    def apply(self) -> None:
        for file_list in self.duplicate_files:
            # master_file = self._get_master_file(file_list)
            master_file, link_list, del_list, ignore_list = self._get_sorted_files(file_list)
            oldest_mod_time = self._get_oldest_mod_time(file_list)
            if self.use_oldest_mod_date:
                replace_date_modifed(master_file, oldest_mod_time)
                for file_path in ignore_list:
                    replace_date_modifed(file_path, oldest_mod_time)
            set_sys_links(master_file, link_list)
            for del_path in del_list:
                try:
                    send2trash(del_path)
                except PermissionError:
                    print("PermissionError, file not deleted: " + del_path)
                except Exception as F:
                    print(str(F))
                    print(del_path)
                    # os.remove(del_path)

    # run a callback with multiple lists
    # files objs deleted and files made system links
    # also a callback on the current file
    # use file objs in the 2 lists
    def apply_finish(self) -> None:
        for file_list in self.duplicate_files:
            # master_file = self._get_master_file(file_list)
            master_file, link_list, del_list = self._get_sorted_files(file_list)
            set_sys_links(master_file, link_list)
            for del_path in del_list:
                try:
                    send2trash(del_path)
                except PermissionError:
                    print("PermissionError, file not deleted: " + del_path)
                except Exception as F:
                    print(str(F))
                    print(del_path)
                    # os.remove(del_path)

    def apply_old(self) -> None:
        for file_list in self.duplicate_files:
            # master_file = self._get_master_file(file_list)
            master_file, link_list, del_list = self._get_sorted_files(file_list)
            set_sys_links(master_file, link_list)
            for del_path in del_list:
                try:
                    send2trash(del_path)
                except PermissionError:
                    print("PermissionError, file not deleted: " + del_path)
                except Exception as F:
                    print(str(F))
                    print(del_path)
                    # os.remove(del_path)
    
    def _get_master_file(self, file_list: list) -> str:
        for file_path in file_list:
            if self.found_file_objs[file_path].get_mark() == FileMarks.MASTER:
                return file_path
    
    def _get_sorted_files(self, file_list: list) -> tuple:
        master_file, link_list, del_list, ignore_list = "", [], [], []
        for file_path in file_list:
            file_obj_mark = self.found_file_objs[file_path].get_mark()
            if file_obj_mark == FileMarks.LINK:
                link_list.append(file_path)
            elif file_obj_mark == FileMarks.DELETE:
                del_list.append(file_path)
            elif file_obj_mark == FileMarks.MASTER:
                master_file = file_path
            elif file_obj_mark == FileMarks.IGNORE:
                ignore_list.append(file_path)
        return master_file, link_list, del_list, ignore_list
    
    def get_dup_list(self, file_path: str) -> list:
        for dup_list in self.duplicate_files:
            if file_path in dup_list:
                return dup_list

    def add_search_dir(self, search_dir: str) -> None:
        if os.path.isdir(search_dir) and search_dir not in self.search_directory_list:
            self.search_directory_list.append(search_dir)

    def add_exclude_dir(self, directory: str) -> None:
        if os.path.isdir(directory) and directory not in self.exclude_directory_list:
            self.exclude_directory_list.append(directory)

    def add_exclude_ext(self, file_ext: str) -> None:
        if not file_ext.startswith("."):
            file_ext = "." + file_ext
        if file_ext not in self.exclude_ext_list:
            self.exclude_ext_list.append(file_ext)

    def add_ext(self, file_ext: str) -> None:
        if not file_ext.startswith("."):
            file_ext = "." + file_ext
        if file_ext not in self.ext_list:
            self.ext_list.append(file_ext)

    def start_search(self, total_file_count: bool = False) -> None:
        if total_file_count or self.total_file_count == 0:
            self.get_total_file_count()
        self._files_scanned = 0
        search_threads = []
        for search_dir in self.search_directory_list:
            search_thread = Thread(target=self._search_directory, args=(search_dir, ))
            search_thread.start()
            search_threads.append(search_thread)
            # self._search_directory(search_dir)
            
        for search_thread in search_threads:
            search_thread.join()
            
        print("FINISHED")
        self._run_scan_finished_callback()

    def reset(self) -> None:
        self.duplicate_files = []
        self.found_file_list = []
        self.file_size_dict = {}
        self.file_hash_dict = {}
        self.total_file_count = 0
        self._files_scanned = 0
        self.total_size = 0
        self.space_saved = 0
        self.new_size = 0
        self._stopping = False

    def get_total_file_count(self) -> int:
        file_count = 0
        for search_dir in self.search_directory_list:
            file_count += self._get_total_file_count_dir(search_dir)
        self.total_file_count = file_count
        return file_count
    
    def _check_quit(self):
        if self._stopping:
            quit()

    def _search_directory(self, directory: str) -> None:
        self._check_quit()
        path_list = os.listdir(directory)
        # print("SCANNING DIRECTORY: " + directory)
        for path in path_list:
            self._check_quit()
            full_path = os.path.join(directory, path)
            if os.path.isdir(full_path):
                if is_junction(full_path):
                    print("SKIPPING DIR JUNCTION: " + full_path)
                    continue
                # if not is_junction(full_path) and full_path not in self.exclude_directory_list:
                if full_path not in self.exclude_directory_list:
                    # if not os.path.islink(full_path):
                    try:
                        self._search_directory(full_path)
                    except PermissionError:
                        pass
            elif self._valid_ext(full_path) and not self._check_link(full_path):
                file_obj = File(full_path)
                self.found_file_objs[full_path] = file_obj
                self.found_file_list.append(full_path)
                for found_file in self.found_file_list:
                    if found_file == full_path:
                        continue
                    self._check_quit()
                    ass = self._compare_file(found_file, full_path)
                    if ass:
                        # print("FOUND DUPLICATE FILE:\n\t" + found_file + "\n\t" + full_path)
                        self._add_duplicate_file(found_file, full_path)
                        # file_obj = File(full_path)
                        # self.found_file_objs[full_path] = file_obj
            # else:
            #     print("SKIPPING SYSTEM LINK: " + full_path)
                # self._run_file_scanned_callback()

    def _get_total_file_count_dir(self, directory: str) -> int:
        try:
            file_count = 0
            path_list = os.listdir(directory)
            for path in path_list:
                full_path = os.path.join(directory, path)
                if os.path.isdir(full_path):
                    if is_junction(full_path):
                        print("SKIPPING DIR JUNCTION: " + full_path)
                        continue
                    file_count += self._get_total_file_count_dir(full_path)
                # elif not os.path.islink(full_path):
                # elif self._valid_ext(full_path) and not (self.ignore_links and os.path.islink(full_path)):
                elif self._valid_ext(full_path) and not self._check_link(full_path):
                    file_count += 1
            return file_count
        except PermissionError:
            return 0

    def _add_duplicate_file(self, compared_file: str, duplicate_file: str):
        for file_list in self.duplicate_files:
            self._check_quit()
            if compared_file in file_list:
                file_list.append(duplicate_file)
                break
        else:
            file_list = [compared_file, duplicate_file]
            self.duplicate_files.append(file_list)
            # self._update_file_size_estimates(compared_file)
            # self._update_file_size_estimates(duplicate_file)
            
        self._run_dup_found_callback(file_list)
        
    # dont use, not finished
    # thinking of calling this whenever a file is added to the dup file list in the api
    # instead of the ui right now
    def _update_file_size_estimates(self, file_path: str) -> None:
        file_size = self._get_file_size(file_path)
        
        for dup_list in self.duplicate_files:
            
            if file_path == dup_list[0]:
                break
            start_file_size = self._get_file_size(dup_list[0])
            self.new_size += start_file_size
            list_size = 0
            for file_path in dup_list:
                file_size = self._get_file_size(file_path)
                list_size += file_size
            self.total_size += list_size
            self.space_saved += (list_size - start_file_size)

    def _compare_file(self, compare_file_path: str, new_file_path: str) -> bool:
        compare_file_size = self._get_file_size(compare_file_path)
        new_file_size = self._get_file_size(new_file_path)
        self._run_file_scanned_callback()
        if compare_file_size == 0 and new_file_size == 0:
            return False
        if compare_file_size == new_file_size:
            if self._stopping:
                quit()
            return self._compare_file_hash(compare_file_path, new_file_path)
        return False

    def _compare_file_hash(self, compare_file_path: str, new_file_path: str) -> bool:
        compare_file_hash = self.file_hash_dict[compare_file_path] \
            if compare_file_path in self.file_hash_dict else self._make_hash(compare_file_path)
        return compare_file_hash == self._make_hash(new_file_path)

    def _make_hash(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as file_io:
                sha = hashlib.sha256()
                file_buffer = file_io.read(BLOCKSIZE)
                while len(file_buffer) > 0:
                    sha.update(file_buffer)
                    file_buffer = file_io.read(BLOCKSIZE)
                file_hash = sha.hexdigest()
                self.file_hash_dict[file_path] = file_hash
                return file_hash
        except FileNotFoundError:
            return ""
        
    def _make_hash_old(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                md5 = hashlib.md5()
                for chunk in iter(lambda: f.read(128 * md5.block_size), b""):
                    md5.update(chunk)
                file_hash = md5.hexdigest()
                self.file_hash_dict[file_path] = file_hash
                return file_hash
        except FileNotFoundError:
            return ""
        
    def _get_file_size(self, file_path: str) -> int:
        file_size = self.file_size_dict[file_path] \
            if file_path in self.file_size_dict else self._get_file_size_io(file_path)
        return file_size
        
    def _get_file_size_io(self, file_path: str) -> int:
        if not self._check_link(file_path):
            file_size = os.path.getsize(file_path)
            self.file_size_dict[file_path] = file_size
            self.total_size += file_size
            return file_size
        return 0
        
    def _valid_ext(self, file_path: str) -> bool:
        valid_ext = False
        file_ext = os.path.splitext(file_path)[1]
        if not self.ext_list or file_ext in self.ext_list:
            valid_ext = True
        if file_ext in self.exclude_ext_list:
            valid_ext = False
        return valid_ext
    
    def _check_link(self, file_path: str) -> bool:
        return self.ignore_links and os.path.islink(file_path)


def set_sys_links(master_file: str, file_list: list) -> None:
    if not os.path.exists(master_file):
        return
    for file_path in file_list:
        if file_path != master_file:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    os.symlink(master_file, file_path)
                    print("Set system link: " + file_path)
                except PermissionError as F:
                    print("Unable to remove file: " + file_path + "\n" + str(F))
                
                
def backup_file(file_path):
    backup_file_path = file_path + ".bak"
    if os.path.exists(backup_file_path):
        i = 0
        while True:
            backup_file_path = file_path + ".bak" + str(i)
            if not os.path.exists(backup_file_path):
                break
        i += 1
    os.rename(file_path, backup_file_path)
    
                
def is_junction(path: str) -> bool:
    try:
        if os.path.isdir(path):
            return bool(os.readlink(path))
    except OSError:
        return False


def get_date_modified(file_path: str) -> float:
    if os.name == "nt":
        if os.path.isfile(file_path):
            return os.path.getmtime(file_path)
    else:
        return os.stat(file_path).st_mtime
    return -1.0


def get_date_modified_datetime(file_path: str) -> datetime.datetime:
    unix_time = get_date_modified(file_path)
    mod_time = datetime.datetime.fromtimestamp(unix_time)
    return mod_time


def replace_date_modifed(file_path: str, mod_time: float) -> bool:
    try:
        os.utime(file_path, (mod_time, mod_time))
        return True
    except FileNotFoundError:
        return False

