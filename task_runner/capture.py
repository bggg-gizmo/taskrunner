"""Pixel-accurate selection in a screenshot of the entire virtual desktop."""
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QBrush
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QWidget
from .paths import data_root


def capture_desktop() -> tuple[Path, int, int]:
    """The virtual desktop bounding box can begin at negative X/Y on multi-monitor rigs."""
    import mss
    from mss.tools import to_png
    dest = data_root() / "captures"
    dest.mkdir(parents=True,exist_ok=True)
    file = dest / f"capture-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.png"
    with mss.mss() as screen:
        geometry = screen.monitors[0]
        shot = screen.grab(geometry)
        to_png(shot.rgb,shot.size,output=str(file))
    return file, geometry["left"], geometry["top"]


class ImageSelection(QWidget):
    changed=Signal()
    def __init__(self, pixmap):
        super().__init__()
        self.image=pixmap
        self.begin=None
        self.end=None
        self.setMouseTracking(True)
        self.setMinimumSize(650,300)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def placement(self):
        if self.image.isNull(): return QRect()
        scale=min(self.width()/self.image.width(),self.height()/self.image.height())
        w=int(self.image.width()*scale);h=int(self.image.height()*scale)
        return QRect((self.width()-w)//2,(self.height()-h)//2,w,h)

    def pixel(self, point):
        frame=self.placement()
        if frame.isNull(): return QPoint()
        x=min(self.image.width()-1,max(0,round((point.x()-frame.left())*self.image.width()/frame.width())))
        y=min(self.image.height()-1,max(0,round((point.y()-frame.top())*self.image.height()/frame.height())))
        return QPoint(x,y)

    def display_point(self, pixel):
        r=self.placement()
        return QPoint(round(r.left()+pixel.x()*r.width()/self.image.width()),round(r.top()+pixel.y()*r.height()/self.image.height()))

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('#050817'))
        painter.drawPixmap(self.placement(),self.image)
        if self.begin is not None and self.end is not None:
            a=self.display_point(self.begin);b=self.display_point(self.end)
            sel=QRect(a,b).normalized()
            painter.setPen(QPen(QColor('#00f5e9'),2,Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(0,245,233,40)))
            if sel.width()<5 and sel.height()<5:
                painter.drawEllipse(a,9,9)
            else: painter.drawRect(sel)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.begin=self.pixel(event.position().toPoint());self.end=self.begin
            self.update();self.changed.emit()

    def mouseMoveEvent(self,event):
        if self.begin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.end=self.pixel(event.position().toPoint())
            self.update();self.changed.emit()

    def mouseReleaseEvent(self,event):
        if self.begin is not None and event.button()==Qt.MouseButton.LeftButton:
            self.end=self.pixel(event.position().toPoint())
            self.update();self.changed.emit()

    def selected_rect(self):
        if self.begin is None or self.end is None:return None
        return QRect(self.begin,self.end).normalized()


class CaptureDialog(QDialog):
    def __init__(self,file:Path,left:int,top:int,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select exact screen position / region")
        self.resize(1100,730)
        self.file=file;self.left=left;self.top=top
        self.selection=None
        layout=QVBoxLayout(self)
        self.help=QLabel("Click for a pixel target, or drag to select an exact rectangular region. Coordinates include secondary monitors.")
        layout.addWidget(self.help)
        self.image=ImageSelection(QPixmap(str(file)))
        self.image.changed.connect(self.update_detail)
        layout.addWidget(self.image,1)
        bottom=QHBoxLayout()
        self.details=QLabel("No selection")
        bottom.addWidget(self.details,1)
        cancel=QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        use=QPushButton("Use selection")
        use.clicked.connect(self.accept_selection)
        bottom.addWidget(cancel);bottom.addWidget(use)
        layout.addLayout(bottom)

    def update_detail(self):
        r=self.image.selected_rect()
        if r is None:return
        cx=self.left+r.center().x();cy=self.top+r.center().y()
        self.details.setText(f"Target: X={cx}, Y={cy}  |  Selected region: {r.width()+1} × {r.height()+1} pixels")

    def accept_selection(self):
        r=self.image.selected_rect()
        if r is None:return
        self.selection={"x":self.left+r.center().x(),"y":self.top+r.center().y(),
                        "region":(r.left(),r.top(),r.width()+1,r.height()+1),"screenshot":str(self.file)}
        self.accept()

    def reference_region(self, minimum_size: int = 48):
        """Avoid unusable one-pixel templates when the user single-clicks."""
        if not self.selection:return None
        x,y,w,h = self.selection['region']
        from PIL import Image
        with Image.open(self.file) as image:
            width,height=image.size
        wanted_w=min(width,max(int(minimum_size),w))
        wanted_h=min(height,max(int(minimum_size),h))
        left=min(max(0,x+(w-wanted_w)//2),width-wanted_w)
        top=min(max(0,y+(h-wanted_h)//2),height-wanted_h)
        return left,top,wanted_w,wanted_h

    def save_region(self):
        bounds=self.reference_region()
        if bounds is None:return None
        from PIL import Image
        x,y,w,h=bounds
        path=data_root()/"captures"/f"reference-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.png"
        with Image.open(self.file) as image:
            image.crop((x,y,x+w,y+h)).save(path)
        return path
