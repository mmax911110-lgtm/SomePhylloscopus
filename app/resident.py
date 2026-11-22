"""pystray bridge. All Tk operations stay on the application's main thread."""
from .i18n import tr
from pathlib import Path
import sys,threading,queue

class Tray:
    def __init__(self,app):
        vendor=Path(__file__).resolve().parents[1]/'vendor'
        if str(vendor)not in sys.path:sys.path.insert(0,str(vendor))
        import pystray
        from .scene import frame
        self.actions=queue.Queue();self.ready=threading.Event();self.failed=None
        self.icon=pystray.Icon('some_leaf_warbler',frame('perch',width=128),
            tr('某种柳莺 · 后台待机，模型已保留'),pystray.Menu(
                pystray.MenuItem(tr('回来找鸟 · 打开窗口'),lambda:self.actions.put('restore'),default=True),
                pystray.MenuItem(tr('彻底退出 · 释放缓存'),lambda:self.actions.put('exit'))))
        def run():
            try:self.icon.run(setup=lambda icon:self.ready.set())
            except Exception as exc:
                self.failed=exc
                app.logger.exception('托盘运行线程失败')
                self.actions.put('failed')
        self.thread=threading.Thread(target=run,name='willow-tray',daemon=True);self.thread.start()
    def show(self):
        if self.failed:raise RuntimeError(str(self.failed))
        if not self.ready.is_set():return False
        self.icon.visible=True;return True
    def hide(self):
        if self.ready.is_set()and not self.failed:self.icon.visible=False
    def close(self):
        self.icon.stop()
