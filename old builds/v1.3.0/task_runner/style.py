"""Functional Qt UI skin: restrained vaporwave with readable controls."""
APP_STYLE = r'''
QWidget { background-color: #080e20; color: #e8efff; font: 10pt "Segoe UI"; }
QMainWindow,QDialog { background-color: #080e20; }
QLabel#Hero { font: bold 26pt "Segoe UI"; color: #33f3ec; }
QLabel#SectionTitle { font: bold 15pt "Segoe UI"; color: #ff71dd; }
QLabel#Muted { color: #9eb2d5; }
QFrame#Panel { border: 1px solid #32436a; border-radius: 8px; background-color: #111c34; }
QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QDateTimeEdit,QTimeEdit,QListWidget,QTableWidget {
    border: 1px solid #344e75; border-radius: 5px; padding: 6px;
    selection-background-color: #9f3dd1; background-color: #101a31; color: #f2f4ff;
}
QTableWidget { gridline-color: #293a5b; alternate-background-color: #14223c; }
QHeaderView::section { background-color: #1d3152; color: #30e8ec; border: 0; border-bottom: 1px solid #455178; padding: 9px; }
QPushButton { background-color: #202e50; border: 1px solid #465b82; border-radius: 5px; padding: 9px 11px; }
QPushButton:hover { background-color: #344871; border-color: #42eceb; }
QPushButton:pressed { background-color: #6c3394; }
QPushButton#Primary { background-color: #1b667b; border: 1px solid #2de1e7; font-weight: bold; }
QPushButton#Danger { background-color: #57213e; border: 1px solid #df4e7c; }
QPushButton:disabled { color: #64708d; background-color: #161e30; }
QTabBar::tab { background-color: #14203b; padding: 9px 16px; border: 1px solid #344c72; }
QTabBar::tab:selected { background-color: #2d315d; color: #39f5ea; }
QCheckBox::indicator { width: 17px; height: 17px; }
QGroupBox { border: 1px solid #32456b; border-radius: 6px; margin-top: 13px; padding-top: 10px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #ff71dd; }
QStatusBar { background-color: #1c1640; color: #d2daff; }
QScrollBar:vertical { background-color: #0d182a; width: 12px; }
QScrollBar::handle:vertical { background-color: #394775; border-radius: 4px; }
QToolTip { background-color: #293150; color: white; }
'''
