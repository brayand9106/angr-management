
import sys
import os

from PySide.QtGui import QMainWindow, QTabWidget, QFileDialog, QProgressBar
from PySide.QtCore import Qt, QSize, QEvent

import angr

from ..logic import GlobalInfo
from ..data.instance import Instance
from .menus.file_menu import FileMenu
from .workspace import Workspace
from .dialogs.load_binary import LoadBinary
from .dialogs.new_state import NewState
from .toolbars.states_toolbar import StatesToolbar


class MainWindow(QMainWindow):
    """
    The main window of angr management.
    """
    def __init__(self, file_to_open=None, parent=None):
        super(MainWindow, self).__init__(parent)

        GlobalInfo.main_window = self

        # initialization
        self.caption = "angr Management"
        self.setMinimumSize(QSize(800, 800))
        self.setDockNestingEnabled(True)

        self.workspace = None

        self._states_toolbar = None  # type: StatesToolbar
        self._progressbar = None  # type: QProgressBar

        self._status = ""
        self._progress = None

        self._init_menus()
        self._init_toolbars()
        self._init_statusbar()
        self._init_workspace()

        # I'm ready to show off!
        self.show()

        self.status = "Ready."

        if file_to_open is not None:
            # load a binary
            self._open_loadbinary_dialog(file_to_open)

    #
    # Properties
    #

    @property
    def caption(self):
        return self.getWindowTitle()

    @caption.setter
    def caption(self, v):
        self.setWindowTitle(v)

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, v):
        self._status = v

        self.statusBar().showMessage(v)

    @property
    def progress(self):
        return self._progress

    @progress.setter
    def progress(self, v):
        self._progress = v
        self._progressbar.show()
        self._progressbar.setValue(v)

    #
    # Dialogs
    #

    def _open_loadbinary_dialog(self, file_to_open):
        load_binary_dialog = LoadBinary(file_to_open)
        load_binary_dialog.exec_()

        if load_binary_dialog.cfg_args is not None:
            # load the binary
            self._load_binary(file_to_open, cfg_args=load_binary_dialog.cfg_args)

    def open_newstate_dialog(self):
        new_state_dialog = NewState(self.workspace, parent=None)
        new_state_dialog.exec_()

    #
    # Widgets
    #

    def _init_statusbar(self):

        self._progressbar = QProgressBar()

        self._progressbar.setMinimum(0)
        self._progressbar.setMaximum(100)
        self._progressbar.hide()

        self.statusBar().addPermanentWidget(self._progressbar)

    def _init_toolbars(self):

        self._states_toolbar = StatesToolbar(self)

        self.addToolBar(Qt.TopToolBarArea, self._states_toolbar.qtoolbar())

    #
    # Menus
    #

    def _init_menus(self):
        fileMenu = FileMenu(self)
        self.menuBar().addMenu(fileMenu.qmenu())

    #
    # Workspace
    #

    def _init_workspace(self):
        wk = Workspace(self)
        self.workspace = wk

        right_dockable_views = [ dock for dock in self.workspace.dockable_views
                                 if dock.widget().default_docking_position == 'right' ]

        for d0, d1 in zip(right_dockable_views, right_dockable_views[1:]):
            self.tabifyDockWidget(d0, d1)
        right_dockable_views[0].raise_()

        self.setTabPosition(Qt.RightDockWidgetArea, QTabWidget.North)

    #
    # Event
    #

    def event(self, event):

        if event.type() == QEvent.User:
            # our event callback

            try:
                event.result = event.execute()
            except Exception:
                event.exception = sys.exc_info()
            event.event.set()

            return True

        return super(MainWindow, self).event(event)

    #
    # Actions
    #

    def reload(self):
        self.workspace.reload()

    def load_binary(self):

        # Open File window
        file_path, _ = QFileDialog.getOpenFileName(self, "Open a binary", ".",
                                                   "All executables (*);;Windows PE files (*.exe);;Core Dumps (*.core)",
                                                   )

        if os.path.isfile(file_path):
            self._open_loadbinary_dialog(file_path)


    def quit(self):
        self.close()

    #
    # Other public methods
    #

    def progress_done(self):
        self._progress = None
        self._progressbar.hide()

    #
    # Private methods
    #

    def _load_binary(self, file_path, cfg_args=None):

        if cfg_args is None:
            cfg_args = { }

        inst = Instance(project=angr.Project(file_path, load_options={'auto_load_libs': False}))
        self.workspace.set_instance(inst)
        inst.initialize(cfg_args=cfg_args)