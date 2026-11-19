"""A modal card in the original window, so the same animated bird can land on it."""
import tkinter as tk
import math
import time
from PIL import ImageTk

class ExitDialog:
    def __init__(self,app):
        self.app=app;self.root=app.window;self.closed=False;self.after_id=None;self.previous_focus=self.root.focus_get()
        self._attention_started=None;self._last_beep=-float('inf');self._sway=0.;self._fallback_item=None
        self.panel=tk.Frame(self.root,bg='#fffdf2',highlightbackground='#a5b77a',highlightthickness=2)
        self.panel.place(relx=.5,rely=.5,anchor='center',width=min(self.root.winfo_width()-40,app._px(620)))
        fam=app.family;pad=app._px(22)
        self.top=tk.Canvas(self.panel,height=app._px(94),bg='#fffdf2',highlightthickness=0)
        self.top.pack(fill='x',padx=app._px(16),pady=(app._px(12),0))
        tk.Label(self.panel,text='这就要出门找鸟啦？',font=(fam,17,'bold'),fg='#45682c',bg='#fffdf2').pack(pady=(0,app._px(14)))
        self.exit_button=self._option('彻底退出','释放缓存，下次要重新翻《中国野生鸟类手册》',app.quit_application,False)
        self.background_button=self._option('推到后台（要去找鸟）','占用缓存，下次打开找得更快。',app.push_to_background,True)
        self.note=tk.Label(self.panel,text='后台会保留内存和显存；点托盘小鸟或再点 EXE 就回来。',font=(fam,9),fg='#78816c',bg='#fffdf2',wraplength=app._px(570))
        self.note.pack(padx=pad,pady=(app._px(8),app._px(4)))
        self.cancel_button=tk.Button(self.panel,text='再看一会儿  ·  Esc',command=self.cancel,font=(fam,10),fg='#687550',bg='#fffdf2',activebackground='#eef2df',relief='flat',bd=0,cursor='hand2')
        self.cancel_button.pack(pady=(0,app._px(12)))
        self.panel.update_idletasks();self.panel.grab_set();self.background_button.focus_set()
        self.escape_binding=self.root.bind('<Escape>',lambda e:(self.cancel(),'break')[1],add='+')
        self.panel.bind('<Escape>',lambda e:self.cancel());self.panel.bind('<Configure>',self._position)
        self.outside_binding=self.root.bind('<Button-1>',self._outside_click,add='+')
        self._position();self._start_bird()
    def _option(self,title,subtitle,callback,primary):
        bg='#edf3df'if primary else'#f6f2e6'
        box=tk.Frame(self.panel,bg=bg,highlightbackground='#b9ca98'if primary else'#ded8c4',highlightthickness=1,cursor='hand2',takefocus=True)
        box.pack(fill='x',padx=self.app._px(22),pady=self.app._px(5))
        title_label=tk.Label(box,text=title,font=(self.app.family,13,'bold'),fg='#426326',bg=bg,cursor='hand2')
        title_label.pack(anchor='w',padx=self.app._px(16),pady=(self.app._px(11),self.app._px(4)))
        small=tk.Label(box,text=subtitle,font=(self.app.family,10),fg='#78816c',bg=bg,cursor='hand2',anchor='w',justify='left',wraplength=self.app._px(550))
        small.pack(anchor='w',padx=self.app._px(16),pady=(0,self.app._px(12)))
        for item in (box,title_label,small):item.bind('<Button-1>',lambda e:callback())
        box.bind('<Return>',lambda e:callback());box.bind('<space>',lambda e:callback());box.bind('<Escape>',lambda e:self.cancel())
        box.bind('<FocusIn>',lambda e:box.configure(highlightbackground='#507b2d',highlightthickness=2))
        box.bind('<FocusOut>',lambda e:box.configure(highlightbackground='#b9ca98'if primary else'#ded8c4',highlightthickness=1))
        return box
    def _position(self,event=None):
        if self.closed:return
        self._draw_branches(self._sway)

    def _draw_branches(self,sway=0.):
        """Only the light Canvas ornaments move; buttons never move under a click."""
        P=self.app._px;w=self.top.winfo_width();y=P(78);dx=sway*P(5);dy=sway*P(2)
        self.top.delete('twig')
        # A tapered, forked branch rather than a straight ruler beneath the bird.
        points=(P(46)+dx,y+P(3)+dy,w*.28+dx,y-P(2)+dy,w*.6+dx,y+dy,w-P(44)+dx,y-P(10)+dy,
                w*.62+dx,y+P(4)+dy,w*.27+dx,y+P(3)+dy)
        self.top.create_polygon(*points,fill='#7a6841',smooth=True,splinesteps=18,tags='twig')
        self.top.create_line(P(62)+dx,y+dy,w*.4+dx,y+P(1)+dy,w-P(65)+dx,y-P(8)+dy,
                             fill='#b39a66',width=max(1,P(1)),smooth=True,tags='twig')
        for f,side in ((.19,-1),(.28,1),(.73,-1),(.82,1)):
            x=w*f+dx;tipx=x+side*P(25);tipy=y-P(21)+dy
            self.top.create_line(x,y+dy,x+side*P(12),y-P(8)+dy,tipx,tipy,
                                 fill='#7a6841',width=max(1,P(2)),smooth=True,tags='twig')
            self._leaf(self.top,tipx,tipy,side,P(23),P(8),'twig')
        if self.app.scene is not None:
            base=(self.panel.winfo_x(),self.panel.winfo_y())
            anchors=[(base[0]+self.top.winfo_x()+w*f+dx,base[1]+self.top.winfo_y()+y-P(1)+dy)for f in (.38,.55,.68)]
            self.app.scene.dialog_anchors=anchors
        if self._fallback_item is not None:
            jump=0.
            if self._attention_started is not None:
                u=min(1.,max(0.,(time.monotonic()-self._attention_started)/1.2))
                jump=abs(math.sin(u*3*math.pi))*P(17)
            self.top.coords(self._fallback_item,w*.5+dx,P(48)+dy-jump)

    @staticmethod
    def _leaf(canvas,x,y,direction,length,width,tag):
        canvas.create_polygon(x,y,x+direction*length*.45,y-width,x+direction*length,y-width*.5,
                              x+direction*length*.52,y+width*.4,fill='#93ab58',outline='#748d42',
                              smooth=True,splinesteps=12,tags=tag)
        canvas.create_line(x,y,x+direction*length*.82,y-width*.35,fill='#c2cd8d',tags=tag)

    def _outside_click(self,event):
        if self.closed:return
        x,y=self.panel.winfo_rootx(),self.panel.winfo_rooty()
        if not (x<=event.x_root<x+self.panel.winfo_width() and y<=event.y_root<y+self.panel.winfo_height()):
            self.notify_attention()
            return 'break'

    def notify_attention(self):
        """Repeated close: familiar Windows alert, one bounded twig/bird animation."""
        if self.closed or self.app.closing:return
        self.panel.lift()
        focus=self.root.focus_get()
        if focus is None or not str(focus).startswith(str(self.panel)+'.'):
            self.background_button.focus_set()
        now=time.monotonic()
        if now-self._last_beep>=.65:
            self._last_beep=now
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
            except (ImportError,RuntimeError,OSError):
                self.root.bell()
        if self.after_id is not None:return
        self._attention_started=now
        scene=self.app.scene
        if scene is not None and not scene.closed:
            scene.dialog_attention(duration=1.2)
        self._attention_tick()

    def _attention_tick(self):
        self.after_id=None
        if self.closed:return
        u=min(1.,max(0.,(time.monotonic()-self._attention_started)/1.2))
        self._sway=math.sin(u*6*math.pi)*(1.-u)
        self._draw_branches(self._sway)
        # Two restrained border pulses; no full-window flashing.
        blend=math.sin(u*2*math.pi)**2
        start=(165,183,122);end=(86,124,47)
        colour='#'+''.join(f'{round(a+(b-a)*blend):02x}'for a,b in zip(start,end))
        self.panel.configure(highlightbackground=colour)
        if u<1.:self.after_id=self.root.after(30,self._attention_tick)
        else:self._attention_started=None;self._sway=0.
    def _start_bird(self):
        scene=self.app.scene
        if scene is not None and not scene.closed:
            scene.take_off(now=__import__('time').monotonic());scene.next_fidget=0
        else:
            from .scene import frame
            self.photo=ImageTk.PhotoImage(frame('perch',width=self.app._px(96)),master=self.root)
            self._fallback_item=self.top.create_image(self.top.winfo_width()*.5,self.app._px(48),image=self.photo)
    def set_message(self,text):
        if not self.closed:self.note.configure(text=text)
    def cancel(self):
        self.app._background_pending=False
        self.close();self.app.exit_dialog=None
    def close(self):
        if self.closed:return
        self.closed=True
        if self.after_id is not None:
            self.root.after_cancel(self.after_id);self.after_id=None
        if getattr(self,'escape_binding',None):self.root.unbind('<Escape>',self.escape_binding)
        if getattr(self,'outside_binding',None):self.root.unbind('<Button-1>',self.outside_binding)
        if self.app.scene is not None:
            self.app.scene.cancel_dialog_attention()
            self.app.scene.dialog_anchors=None
            self.app.scene.until=0
        try:self.panel.grab_release();self.panel.destroy()
        except tk.TclError:pass
        try:
            if self.previous_focus is not None and self.previous_focus.winfo_exists():self.previous_focus.focus_set()
        except tk.TclError:pass
