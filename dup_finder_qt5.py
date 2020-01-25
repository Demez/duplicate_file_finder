import os
import sys
import datetime
import argparse
import webbrowser
from enum import Enum
from time import perf_counter
from threading import Thread
from dup_finder import DuplicateFinder, File, FileMarks, is_junction

# for pycharm, install pyqt5-stubs, so you don't get 10000 errors for no reason
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtCore import *


def parse_args() -> argparse.Namespace:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--directories", '-d', required=True, nargs="+", help="directories to search")
    arg_parser.add_argument("--exclude", '-ed', default=[], nargs="+", help="directories to exclude")
    arg_parser.add_argument("--ext", '-e', default=[], nargs="+", help="only check files with these extensions")
    arg_parser.add_argument("--ignore_ext", '-i', default=[], nargs="+", help="file extensions to exclude")
    return arg_parser.parse_args()


class MainWindow(QWidget):
    # dup file found?
    sig_dup_found = pyqtSignal(list)
    sig_file_scanned = pyqtSignal(int)
    sig_finished = pyqtSignal()
    sig_apply = pyqtSignal(File, list)
    
    def __init__(self):
        super().__init__()
        self.setLayout(QVBoxLayout())
        self.setWindowTitle("Duplicate File Finder")
        self.dup_finder = DuplicateFinder()
        self.dup_finder_threads = []
        self.dup_files_added_to_list = []
        
        self.progress_bar = QProgressBar()
        
        self.button_start = QPushButton("Start")
        self.button_open_folder = QPushButton("Open folder")
        self.button_open_file = QPushButton("Open file")
        self.button_apply = QPushButton("Apply")
        
        # self.check_view_master = QCheckBox("view master")
        # self.check_view_link = QCheckBox("view system link")
        # self.check_view_ignored = QCheckBox("view ignored")
        self.check_ignore_links = QCheckBox("Ignore system links")
        self.check_use_oldest_date_mod = QCheckBox("Use oldest date modified")
        self.check_use_oldest_date_mod.setToolTip("When replacing files with system links,\n"
                                                  "look for the oldest date modified among them,\n"
                                                  "and set the date modified of the master file to the oldest one")
        
        help_master = "Files marked as Link point to this file"
        help_link = "Create a system link pointing to the Master file"
        help_delete = "Delete the file"
        help_ignore = "Don't do anything with the file"
        
        self.file_mark_button_group = QGroupBox("Default File Mark")
        self.file_mark_button_group.setToolTip("What the first file in a new duplicate file list will be set to on apply")
        file_mark_layout = QVBoxLayout()
        self.file_mark_master = QRadioButton("Master")
        self.file_mark_del = QRadioButton("Delete")
        self.file_mark_ignore = QRadioButton("Ignore")
        self.file_mark_master.setChecked(True)
        self.file_mark_master.setToolTip(help_master)
        self.file_mark_del.setToolTip(help_delete)
        self.file_mark_ignore.setToolTip(help_ignore)
        # self.file_mark_button_group.addButton(self.file_mark_master)
        # self.file_mark_button_group.addButton(self.file_mark_del)
        # self.file_mark_button_group.addButton(self.file_mark_ignore)
        file_mark_layout.addWidget(self.file_mark_master)
        file_mark_layout.addWidget(self.file_mark_del)
        file_mark_layout.addWidget(self.file_mark_ignore)
        self.file_mark_button_group.setLayout(file_mark_layout)
        
        self.file_mark_dup_button_group = QGroupBox("Default Duplicate File Mark")
        self.file_mark_dup_button_group.setToolTip("What any file added to an existing duplicate file list will be set to on apply")
        file_mark_dup_layout = QVBoxLayout()
        self.file_mark_dup_link = QRadioButton("Link")
        self.file_mark_dup_del = QRadioButton("Delete")
        self.file_mark_dup_ignore = QRadioButton("Ignore")
        self.file_mark_dup_link.setChecked(True)
        self.file_mark_dup_link.setToolTip(help_link)
        self.file_mark_dup_del.setToolTip(help_delete)
        self.file_mark_dup_ignore.setToolTip(help_ignore)
        file_mark_dup_layout.addWidget(self.file_mark_dup_link)
        file_mark_dup_layout.addWidget(self.file_mark_dup_del)
        file_mark_dup_layout.addWidget(self.file_mark_dup_ignore)
        self.file_mark_dup_button_group.setLayout(file_mark_dup_layout)
        
        # self.check_view_master.setChecked(True)
        # self.check_view_link.setChecked(True)
        # self.check_view_ignored.setChecked(True)
        self.check_ignore_links.setChecked(True)
        self.check_use_oldest_date_mod.setChecked(True)
        self.check_ignore_links.stateChanged.connect(self.check_ignore_links_changed)
        self.check_use_oldest_date_mod.stateChanged.connect(self.check_oldest_date_changed)
        
        self.button_open_folder.clicked.connect(self.open_folder)
        self.button_open_file.clicked.connect(self.open_file)
        self.button_start.clicked.connect(self.toggle_search)
        self.button_apply.clicked.connect(self.apply)
        
        self.label_total_files = QLabel("Total Files: 0")
        self.label_files_scanned = QLabel("Files Scanned: 0")
        self.label_dups_found = QLabel("Duplicate Files Found: 0")
        self.label_total_size = QLabel("Total Size: 0.0 MB")
        self.label_new_size = QLabel("New Size: 0.0 MB")
        self.label_space_saved = QLabel("Space Saved: 0.0 MB")
        self.file_list = FileList()
        self.list_dup_files = QTreeView()
        self.list_dup_files.setModel(self.file_list)
        header = self.list_dup_files.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        min_size = 20
        header.setMinimumSectionSize(min_size)
        header.resizeSection(2, 40)
        header.resizeSection(3, min_size)
        header.resizeSection(4, min_size)
        header.resizeSection(5, min_size)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        header.setStretchLastSection(False)
        
        self.list_dup_files_layout = QHBoxLayout()
        self.dup_file_btns_layout = QVBoxLayout()
        list_dup_files_layout_widget = QWidget()
        dup_file_btns_widget = QWidget()
        
        self.list_dup_files_layout.setContentsMargins(QMargins(0, 0, 0, 0))
        self.dup_file_btns_layout.setContentsMargins(QMargins(0, 0, 0, 0))
        
        list_dup_files_layout_widget.setLayout(self.list_dup_files_layout)
        dup_file_btns_widget.setLayout(self.dup_file_btns_layout)
        
        self.layout().addWidget(self.progress_bar)
        self.layout().addWidget(self.button_start)
        self.layout().addWidget(self.label_total_files)
        self.layout().addWidget(self.label_files_scanned)
        self.layout().addWidget(self.label_dups_found)
        
        self.layout().addWidget(self.label_total_size)
        self.layout().addWidget(self.label_new_size)
        self.layout().addWidget(self.label_space_saved)
        
        self.layout().addWidget(list_dup_files_layout_widget)
        self.list_dup_files_layout.addWidget(self.list_dup_files)
        self.list_dup_files_layout.addWidget(dup_file_btns_widget)
        
        self.dup_file_btns_layout.addWidget(self.button_open_folder)
        self.dup_file_btns_layout.addWidget(self.button_open_file)
        
        # self.dup_file_btns_layout.addWidget(self.check_view_master)
        # self.dup_file_btns_layout.addWidget(self.check_view_link)
        # self.dup_file_btns_layout.addWidget(self.check_view_ignored)
        self.dup_file_btns_layout.addWidget(self.check_ignore_links)
        self.dup_file_btns_layout.addWidget(self.check_use_oldest_date_mod)
        
        self.dup_file_btns_layout.addWidget(self.file_mark_button_group)
        self.dup_file_btns_layout.addWidget(self.file_mark_dup_button_group)
        
        self.dup_file_btns_layout.addStretch(1)
        self.dup_file_btns_layout.addWidget(self.button_apply)
        
        [self.dup_finder.add_search_dir(arg) for arg in ARGS.directories]
        [self.dup_finder.add_exclude_dir(arg) for arg in ARGS.exclude]
        [self.dup_finder.add_exclude_ext(arg) for arg in ARGS.ignore_ext]
        [self.dup_finder.add_ext(arg) for arg in ARGS.ext]
        
        self.sig_dup_found.connect(self.dup_file_found)
        self.sig_file_scanned.connect(self.file_scanned)
        self.sig_finished.connect(self.scan_finished)
        self.sig_apply.connect(self.file_list.apply_callback)
        
        self.dup_finder.set_file_scanned_callback(self.file_scanned_emit)
        self.dup_finder.set_dup_found_callback(self.dup_file_found_emit)
        self.dup_finder.set_scan_finished_callback(self.scan_finished_emit)
        self.dup_finder.set_apply_callback(self.apply_emit)

        self.total_file_count = 0
        self.label_total_files.setText("Total Files: " + str(self.total_file_count))
        self.color_2 = False
        self.bg_color = QColor("#e6e6e6")  # QColor("#d9d9d9")
        
        self.show()
    
    def closeEvent(self, event):
        event.accept()
        self.dup_finder.stop()
        sys.exit(0)
    
    @pyqtSlot()
    def toggle_search(self) -> None:
        if self.button_start.text() == "Start":
            # self.file_list.model.removeRows(0, self.file_list.model.rowCount())
            self.file_list.reset()
            self.dup_files_added_to_list = []
            self.button_apply.setDisabled(False)
            self.button_apply.setToolTip("")
            self.label_dups_found.setText("Duplicate Files Found: 0")
            self.label_total_size.setText("Total Size: 0.0 MB")
            self.label_new_size.setText("New Size: 0.0 MB")
            self.label_space_saved.setText("Space Saved: 0.0 MB")
            self.dup_finder.reset()
            self.total_file_count = self.dup_finder.get_total_file_count()
            self.label_total_files.setText("Total Files: " + str(self.total_file_count))
            self.progress_bar.setValue(0)
            self.progress_bar.setMaximum(self.total_file_count)
            dup_finder_thread = Thread(target=self.dup_finder.start_search)
            dup_finder_thread.start()
            self.dup_finder_threads.append(dup_finder_thread)
            # self.button_start.setDisabled(True)
            self.button_start.setText("Stop")
            
        elif self.button_start.text() == "Stop":
            self.dup_finder.stop()
            for thread in self.dup_finder_threads:
                if not thread.is_alive():
                    thread.join()
            self.dup_finder_threads = []
            # self.dup_files_added_to_list = []
            self.button_start.setText("Start")
    
    # TODO: have this select the file in file explorer if windows
    @pyqtSlot()
    def open_folder(self) -> None:
        file_path = self.get_selected_item_path()
        if file_path:
            webbrowser.open('file:///' + os.path.split(file_path)[0])
    
    @pyqtSlot()
    def open_file(self) -> None:
        # item = self.list_dup_files.currentItem()
        file_path = self.get_selected_item_path()
        if file_path:
            webbrowser.open('file:///' + file_path)
    
    @pyqtSlot()
    def apply(self) -> None:
        self.dup_finder.apply()
        self.button_apply.setDisabled(True)
        self.button_apply.setToolTip("Need to rescan, doesn't update the list yet")

    @pyqtSlot()
    def check_ignore_links_changed(self) -> None:
        self.dup_finder.ignore_links = self.check_ignore_links.isChecked()

    @pyqtSlot()
    def check_oldest_date_changed(self) -> None:
        self.dup_finder.use_oldest_mod_date = self.check_use_oldest_date_mod.isChecked()
    
    def get_selected_item_row(self) -> int:
        # item = self.list_dup_files.currentItem()
        selected_items = self.list_dup_files.selectedIndexes()
        rows = []
        for selected_item in selected_items:
            rows.append(selected_item.row())
        if rows:
            return rows[0]
    
    def get_selected_item(self) -> File:
        item_row = self.get_selected_item_row()
        item = self.file_list.get_file_obj_row(item_row)
        return item
    
    def get_selected_item_path(self) -> str:
        return self.get_selected_item().path
    
    def file_scanned_emit(self, files_scanned: int) -> None:
        if files_scanned >= self.total_file_count:
            print("hold up")
        self.sig_file_scanned.emit(files_scanned)
    
    def dup_file_found_emit(self, dup_file_list: list) -> None:
        self.sig_dup_found.emit(dup_file_list)
    
    def scan_finished_emit(self) -> None:
        self.sig_finished.emit()
    
    def apply_emit(self, file_obj: File, dup_list: list) -> None:
        self.sig_apply.emit(file_obj, dup_list)
        
    def _get_def_mark(self) -> Enum:
        if self.file_mark_master.isChecked():
            return FileMarks.MASTER
        elif self.file_mark_del.isChecked():
            return FileMarks.DELETE
        elif self.file_mark_ignore.isChecked():
            return FileMarks.IGNORE
        return FileMarks.IGNORE
        
    def _get_def_dup_mark(self) -> Enum:
        if self.file_mark_dup_link.isChecked():
            return FileMarks.LINK
        elif self.file_mark_dup_del.isChecked():
            return FileMarks.DELETE
        elif self.file_mark_dup_ignore.isChecked():
            return FileMarks.IGNORE
        return FileMarks.IGNORE
        
    def dup_file_found(self, dup_file_list: list) -> None:
        start = perf_counter()
        for dup_file in dup_file_list:
            if dup_file not in self.dup_files_added_to_list:
                # start = perf_counter()
                # is_link = os.path.islink(dup_file)
                # if not ARGS.no_defaults and not os.path.islink(dup_file):
                
                ass = self._get_def_mark()
                if not os.path.islink(dup_file):
                    # file_state = FileMarks.MASTER if dup_file_list.index(dup_file) == 0 else ARGS.file_mark_dup
                    file_state = self._get_def_mark() if not dup_file_list.index(dup_file) else self._get_def_dup_mark()
                else:
                    file_state = FileMarks.IGNORE
                    
                for added_dup_file_widget_index in range(0, self.file_list.rowCount()):
                    added_dup_file_widget_item = self.file_list.get_file_obj_row(added_dup_file_widget_index)
                    if added_dup_file_widget_item.path in dup_file_list:
                        self.file_list.insert_item(added_dup_file_widget_index, dup_file, file_state)
                        break
                else:
                    # TODO: maybe check for more variety between colors, so we don't get too similar ones?
                    '''
                    if self.list_dup_files.count():
                        prev_item = self.list_dup_files.item(self.list_dup_files.count() - 1)
                        prev_color = prev_item.background().color().name()
                        while True:
                            hex_color = random_color()
                            # if hex_color != prev_color:
                            if not are_colors_too_similar(hex_color, prev_color):
                                break
                    else:
                        hex_color = random_color()
                    dup_file_widget_item.setBackground(QColor(hex_color))
                    '''
                    # start = perf_counter()
                    if self.color_2:
                        self.file_list.add_item(dup_file, file_state, self.bg_color)
                    else:
                        self.file_list.add_item(dup_file, file_state)
                    # print("time: " + str(perf_counter() - start))
                    self.color_2 = not self.color_2
                self.dup_files_added_to_list.append(dup_file)
        
        self.scan_update()
        print("dup file found time: " + str(perf_counter() - start))
        
    def scan_update(self) -> None:
        self.label_dups_found.setText("Duplicate Files Found: " + str(self.dup_finder.get_duplicate_file_count()))
        self.dup_finder.update_size_estimates()
        self.label_total_size.setText("Total Size: " + str(bytes_to_megabytes(self.dup_finder.total_size)) + " MB")
        self.label_new_size.setText("New Size: " + str(bytes_to_megabytes(self.dup_finder.new_size)) + " MB")
        self.label_space_saved.setText("Space Saved: " + str(bytes_to_megabytes(self.dup_finder.space_saved)) + " MB")
    
    def file_scanned(self, files_scanned: int) -> None:
        self.progress_bar.setValue(files_scanned)
        self.label_files_scanned.setText("Files Scanned: " + str(files_scanned))
        
    def scan_finished(self) -> None:
        self.file_scanned(self.progress_bar.maximum())
        self.scan_update()
        self.button_start.setText("Start")


class FileCheckBox(QStandardItem):
    def __init__(self):
        super().__init__()
        # so we don't hit a recursion error right after checking something
        # since on_check_change is called every time we change the state of a checkbox
        self.recurse_check = False
        self.setCheckable(True)
        self.setEditable(False)


class FileList(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.model = QStandardItemModel()
        self.setSourceModel(self.model)
        self.model.itemChanged.connect(self.on_check_change)
        self._check_master = 3
        self._check_link = 4
        self._check_del = 5
        self.model.setColumnCount(self._check_del)
        self.model.setHorizontalHeaderItem(0, QStandardItem("File Path"))
        self.model.setHorizontalHeaderItem(1, QStandardItem("File Size"))
        # self.model.setHorizontalHeaderItem(2, QStandardItem("File Extension"))
        self.model.setHorizontalHeaderItem(2, QStandardItem("Is Link"))
        self.model.setHorizontalHeaderItem(self._check_master, QStandardItem("M"))
        self.model.setHorizontalHeaderItem(self._check_link, QStandardItem("L"))
        self.model.setHorizontalHeaderItem(self._check_del, QStandardItem("D"))
        ass = self.model.horizontalHeaderItem(0)
        print("uhhh")
        
    def reset(self) -> None:
        self.model.removeRows(0, self.model.rowCount())

    def apply_callback(self, file_obj: File, dup_list: list) -> None:
        item = self.get_file_item(file_obj.path)
        
        if file_obj.get_mark() == FileMarks.MASTER:
            pass
        elif file_obj.get_mark() == FileMarks.LINK:
            # uncheck and make link, or remove if ignore links is checked
            pass
        elif file_obj.get_mark() == FileMarks.DELETE:
            self.model.removeRow(item.Row())

    def remove_item(self, file_path: str) -> None:
        pass
    
    def add_item(self, file_path: str, check_state: Enum = FileMarks.IGNORE, bg_color: QColor = None) -> None:
        # self._add_item_row(self.row, file_path, check_state, bg_color)
        self._add_item_row(self.model.rowCount(), file_path, check_state, bg_color)
    
    def insert_item(self, row_index: int, file_path: str, check_state: Enum = FileMarks.IGNORE) -> None:
        item_at_row = self.model.item(row_index)
        self.model.insertRow(row_index)
        self._add_item_row(row_index, file_path, check_state, item_at_row.background().color())
    
    def _add_item_row(self, row: int, file_path: str, check_state: Enum = FileMarks.IGNORE,
                      bg_color: QColor = None) -> None:
        item_file_path = QStandardItem(file_path)
        # item_date_mod = QStandardItem(get_date_modified_datetime(file_path).strftime("%Y-%m-%d %H:%M:%S"))
        # item_date_mod = QStandardItem(str(get_date_modified_datetime(file_path)))
        item_date_mod = QStandardItem(get_file_size_str(file_path))
        if os.path.islink(file_path):
            item_is_link = QStandardItem("LINK")
        else:
            item_is_link = QStandardItem()
        
        check_master = FileCheckBox()
        check_link = FileCheckBox()
        check_del = FileCheckBox()
        
        item_file_path.setEditable(False)
        item_date_mod.setEditable(False)
        item_is_link.setEditable(False)
        
        if bg_color and bg_color.name() != "#000000":
            item_file_path.setBackground(bg_color)
            item_date_mod.setBackground(bg_color)
            item_is_link.setBackground(bg_color)
            check_master.setBackground(bg_color)
            check_link.setBackground(bg_color)
            check_del.setBackground(bg_color)
            
        self.model.setItem(row, 0, item_file_path)
        self.model.setItem(row, 1, item_date_mod)
        self.model.setItem(row, 2, item_is_link)
        self.model.setItem(row, self._check_master, check_master)
        self.model.setItem(row, self._check_link, check_link)
        self.model.setItem(row, self._check_del, check_del)
        
        # doing this earlier breaks shit since on_check_change would be called before they are added to the model
        if check_state == FileMarks.MASTER:
            check_master.setCheckState(Qt.Checked)
        elif check_state == FileMarks.LINK:
            check_link.setCheckState(Qt.Checked)
        elif check_state == FileMarks.DELETE:
            check_del.setCheckState(Qt.Checked)
    
    @pyqtSlot(QStandardItem)
    def on_check_change(self, item: FileCheckBox) -> None:
        # have to check if it's checked so we don't get a recursion error when we uncheck something
        # if item.isCheckable() and item.checkState() == Qt.Checked:
        if item.isCheckable():
            # TODO: this is causing weird issues (should of seen coming)
            #  really need to just have a fucking horizontal radio button thing for files
            #  or a combo box
            # if item.recurse_check:
            #     item.recurse_check = False
            #     return
            
            model_index = self.model.indexFromItem(item)
            row, column = model_index.row(), model_index.column()
            file_path = self.model.item(row, 0).text()
            file_obj = self.get_file_obj_row(row)

            # if item.checkState() == Qt.Unchecked:
            #     file_obj.set_mark(FileMarks.IGNORE)
            #     return
            
            if column == self._check_master:
                if self.file_obj_set_ignore(item, file_obj, FileMarks.MASTER):
                    return
                dup_list = main_window.dup_finder.get_dup_list(file_path)
                for dup_file_path in dup_list:
                    if dup_file_path != file_path:
                        self.set_check_master(dup_file_path, Qt.Unchecked)
                if file_obj.get_mark() != FileMarks.MASTER:
                    self.set_check_link(file_path, Qt.Unchecked)
                    self.set_check_del(file_path, Qt.Unchecked)
                    self.set_check_master(file_path, Qt.Checked)
                    file_obj.set_mark(FileMarks.MASTER)
                
            elif column == self._check_link:
                if self.file_obj_set_ignore(item, file_obj, FileMarks.LINK):
                    return
                if file_obj.get_mark() != FileMarks.LINK:
                    self.set_check_master(file_path, Qt.Unchecked)
                    self.set_check_del(file_path, Qt.Unchecked)
                    self.set_check_link(file_path, Qt.Checked)
                    file_obj.set_mark(FileMarks.LINK)
                
            elif column == self._check_del:
                if self.file_obj_set_ignore(item, file_obj, FileMarks.DELETE):
                    return
                if file_obj.get_mark() != FileMarks.DELETE:
                    self.set_check_master(file_path, Qt.Unchecked)
                    self.set_check_link(file_path, Qt.Unchecked)
                    self.set_check_del(file_path, Qt.Checked)
                    file_obj.set_mark(FileMarks.DELETE)
            else:
                file_obj.set_mark(FileMarks.IGNORE)
    
    def set_check_master(self, file_path: str, state) -> None:
        self._set_check(file_path, state, self._check_master, FileMarks.MASTER)
    
    def set_check_link(self, file_path: str, state) -> None:
        self._set_check(file_path, state, self._check_link, FileMarks.LINK)
    
    def set_check_del(self, file_path: str, state) -> None:
        self._set_check(file_path, state, self._check_del, FileMarks.DELETE)
    
    def _set_check(self, file_path: str, state, column: int, file_mark: Enum) -> None:
        file_path_item = self.get_file_item(file_path)
        if file_path_item:
            check_item = self.model.item(file_path_item.row(), column)
            if check_item and state != check_item.checkState():
                if state == Qt.Unchecked:
                    set_file_mark(file_path, FileMarks.IGNORE)
                else:
                    set_file_mark(file_path, file_mark)
                check_item.setCheckState(state)
                
    def uncheck_row(self, file_path: str, column_to_keep: int) -> None:
        file_path_item = self.get_file_item(file_path)
        if file_path_item:
            row = file_path_item.row()
            if column_to_keep != self._check_master:
                self.uncheck_column(row, self._check_master)
            if column_to_keep != self._check_link:
                self.uncheck_column(row, self._check_link)
            if column_to_keep != self._check_del:
                self.uncheck_column(row, self._check_del)
    
    # this was a mistake
    def uncheck_row_mistake(self, file_path: str) -> None:
        file_path_item = self.get_file_item(file_path)
        if file_path_item:
            row = file_path_item.row()
            self.uncheck_column(row, self._check_master)
            self.uncheck_column(row, self._check_link)
            self.uncheck_column(row, self._check_del)
    
    def uncheck_column(self, row: int, column: int) -> None:
        check_box = self.model.item(row, column)
        if check_box:
            self.uncheck_item_old(check_box)
            
    @staticmethod
    def uncheck_item_old(check_box: FileCheckBox) -> None:
        check_box.recurse_check = True
        check_box.setCheckState(Qt.Unchecked)
        
    @staticmethod
    def file_obj_set_ignore(item: QStandardItem, file_obj: File, old_file_mark: Enum) -> bool:
        if item.checkState() == Qt.Unchecked:
            if file_obj.get_mark() == old_file_mark:
                file_obj.set_mark(FileMarks.IGNORE)
            return True
        return False
    
    def _get_iter(self) -> iter:
        return range(0, self.model.rowCount())
    
    def get_file_item(self, file_path: str) -> QStandardItem:
        for file_index in self._get_iter():
            item = self.model.item(file_index)
            if item and item.text() == file_path:
                return item
    
    def get_file_row(self, file_path: str) -> int:
        return self.get_file_item(file_path).row()
    
    def get_file_obj_row(self, row_selected: int) -> File:
        return get_file_obj(self.model.item(row_selected, 0).text())
    
    
def get_file_obj(file_path: str) -> File:
    return main_window.dup_finder.found_file_objs[file_path]


def set_file_mark(file_path: str, file_mark: Enum) -> None:
    if file_mark not in FileMarks:
        raise Exception("Unknown Enum: " + str(file_mark))
    get_file_obj(file_path).set_mark(file_mark)


def get_file_size(file_path: str) -> int:
    if not os.path.islink(file_path):
        return os.path.getsize(file_path)


def get_file_size_str(file_path: str) -> str:
    try:
        return str(bytes_to_megabytes(os.path.getsize(file_path))) + " MB"
    except FileNotFoundError:
        return "0 MB"


def bytes_to_megabytes(bytes_: int) -> float:
    if os.name == "nt":
        return round(bytes_ * 0.00000095367432, 3)  # use 1024 multiples for windows
    else:
        return round(bytes_ * 0.000001, 3)


# Back up the reference to the exceptionhook
sys._excepthook = sys.excepthook


def qt_exception_hook(exctype, value, traceback):
    # Print the error and traceback
    print(exctype, value, traceback)
    # Call the normal Exception hook after
    sys._excepthook(exctype, value, traceback)
    sys.exit(1)


# Set the exception hook to our wrapping function
sys.excepthook = qt_exception_hook

if __name__ == "__main__":
    ARGS = parse_args()
    APP = QApplication(sys.argv)
    APP.setDesktopSettingsAware(True)
    main_window = MainWindow()
    try:
        sys.exit(APP.exec_())
    except Exception as F:
        print(F)
        quit()

