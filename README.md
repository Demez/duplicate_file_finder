# duplicate_file_finder

start dup_finder_qt5.py with command line options

```
usage: dup_finder_qt5.py [-h] --directories DIRECTORIES [DIRECTORIES ...]
                         [--exclude EXCLUDE [EXCLUDE ...]]
                         [--ext EXT [EXT ...]]
                         [--ignore_ext IGNORE_EXT [IGNORE_EXT ...]]

required arguments:
  --directories DIRECTORIES [DIRECTORIES ...], -d DIRECTORIES [DIRECTORIES ...]
                        directories to search

optional arguments:
  -h, --help            show this help message and exit
  --exclude EXCLUDE [EXCLUDE ...], -ed EXCLUDE [EXCLUDE ...]
                        directories to exclude
  --ext EXT [EXT ...], -e EXT [EXT ...]
                        only check files with these extensions
  --ignore_ext IGNORE_EXT [IGNORE_EXT ...], -i IGNORE_EXT [IGNORE_EXT ...]
                        file extensions to exclude
```