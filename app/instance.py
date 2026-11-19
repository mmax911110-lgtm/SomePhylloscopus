"""Windows per-user singleton with a bounded JSON wake queue; no model imports."""
import ctypes
from ctypes import wintypes as w
import getpass,hashlib,json,mmap,os

class SingleInstance:
    SIZE=65536
    def __init__(self, namespace='SomeLeafWarbler.Application'):
        self.closed=False;self.primary=False;self.handles=[];self.memory=None
        if os.name!='nt':raise RuntimeError('后台单实例目前仅支持Windows')
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        self.k.CreateMutexW.argtypes=[w.LPVOID,w.BOOL,w.LPCWSTR];self.k.CreateMutexW.restype=w.HANDLE
        self.k.CreateEventW.argtypes=[w.LPVOID,w.BOOL,w.BOOL,w.LPCWSTR];self.k.CreateEventW.restype=w.HANDLE
        self.k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];self.k.WaitForSingleObject.restype=w.DWORD
        for fn in ('ReleaseMutex','SetEvent','CloseHandle'):
            getattr(self.k,fn).argtypes=[w.HANDLE];getattr(self.k,fn).restype=w.BOOL
        identity=namespace+'|'+os.environ.get('USERDOMAIN','')+'|'+getpass.getuser()
        self.name='Local\\Willow_'+hashlib.sha256(identity.encode()).hexdigest()[:32]
        try:
            self.mutex=self._handle(self.k.CreateMutexW(None,False,self.name))
            status=self.k.WaitForSingleObject(self.mutex,0)
            if status not in (0,0x80,0x102):raise ctypes.WinError(ctypes.get_last_error())
            self.primary=status in (0,0x80)
            self.queue_mutex=self._handle(self.k.CreateMutexW(None,False,self.name+'_queue'))
            self.event=self._handle(self.k.CreateEventW(None,False,False,self.name+'_wake'))
            self.memory=mmap.mmap(-1,self.SIZE,tagname=self.name+'_json',access=mmap.ACCESS_WRITE)
        except Exception:self.close();raise
    def _handle(self,h):
        if not h:raise ctypes.WinError(ctypes.get_last_error())
        self.handles.append(h);return h
    def _read(self):
        self.memory.seek(0);n=int.from_bytes(self.memory.read(4),'little')
        if n<=0 or n>self.SIZE-4:return []
        data=json.loads(self.memory.read(n).decode('utf-8'))
        if not isinstance(data,list):raise ValueError('Invalid wake request')
        return data
    def _write(self,requests):
        data=json.dumps(requests,ensure_ascii=False).encode('utf-8')
        if len(data)>self.SIZE-4:raise ValueError('一次唤回传入的照片过多，请在原窗口添加')
        self.memory.seek(0);self.memory.write(len(data).to_bytes(4,'little')+data)
    def notify(self,images=()):
        status=self.k.WaitForSingleObject(self.queue_mutex,1500)
        if status not in (0,0x80):raise RuntimeError('原窗口正在处理唤回请求，请稍后重试')
        try:
            requests=self._read();requests.append({'images':[str(p)for p in images]});self._write(requests)
        finally:self.k.ReleaseMutex(self.queue_mutex)
        ctypes.windll.user32.AllowSetForegroundWindow(w.DWORD(0xffffffff))
        if not self.k.SetEvent(self.event):raise ctypes.WinError(ctypes.get_last_error())
    def poll(self):
        if self.closed or not self.primary or self.k.WaitForSingleObject(self.event,0)!=0:return []
        if self.k.WaitForSingleObject(self.queue_mutex,0)not in (0,0x80):self.k.SetEvent(self.event);return []
        try:requests=self._read();self._write([])
        finally:self.k.ReleaseMutex(self.queue_mutex)
        return [{'images':[s for s in r.get('images',[])if isinstance(s,str)and len(s)<32768]}for r in requests if isinstance(r,dict)]
    def close(self):
        if self.closed:return
        self.closed=True
        if self.memory is not None:self.memory.close()
        if self.primary:self.k.ReleaseMutex(self.mutex)
        for h in reversed(self.handles):self.k.CloseHandle(h)
        self.handles=[]

def foreground(window):
    window.deiconify();window.lift();window.focus_force()
    if os.name=='nt':
        user=ctypes.windll.user32
        user.GetAncestor.argtypes=[w.HWND,w.UINT];user.GetAncestor.restype=w.HWND
        user.SetForegroundWindow.argtypes=[w.HWND];user.SetForegroundWindow.restype=w.BOOL
        user.SetForegroundWindow(user.GetAncestor(window.winfo_id(),2))
