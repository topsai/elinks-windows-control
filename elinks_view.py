import tkinter as tk

BG = "#404040"
BAR = "#323232"
TILE = "#353535"
ORANGE = "#ff7800"
ACCENT = "#ff9800"
TEXT = "#ffffff"
MUTED = "#9e9e9e"
FONT = "Microsoft YaHei UI"
CCT_MIN, CCT_MAX = 2700, 6500


class LampView:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.root.configure(bg=BG)
        self.root.geometry("432x550+35+24")
        self.root.minsize(396, 540)
        self.tab = "CCT"
        self.traces = []
        self.pending = None
        self.settings_window = None

        bar = tk.Frame(self.root, bg=BAR, padx=12, pady=8)
        bar.pack(fill="x")
        self.button(bar, "＋ 搜索设备", lambda: app.run(app.scan)).pack(side="left")
        self.connect_button = self.button(bar, "连接", lambda: app.run(app.toggle), state="disabled")
        self.connect_button.pack(side="right")
        app.device = app.make_device_picker(bar)
        app.device.pack(side="left", fill="x", expand=True, padx=8)

        self.nav = tk.Frame(self.root, bg=BG)
        self.nav.pack(fill="x", padx=10, pady=(5, 0))
        self.page = tk.Frame(self.root, bg=BG)

        bottom = tk.Frame(self.root, bg=BAR, height=67)
        bottom.pack(side="bottom", fill="x")
        bottom.pack_propagate(False)
        for i in range(3):
            bottom.columnconfigure(i, weight=1, uniform="footer")
        self.button(bottom, "查询状态", lambda: app.run(app.query)).grid(row=0, column=0, pady=12)
        self.power_button = self.button(bottom, "⏻", self.toggle_power, font=("Segoe UI Symbol", 21), padx=15, pady=3)
        self.power_button.grid(row=0, column=1, pady=6)
        self.button(bottom, "设置", self.settings).grid(row=0, column=2, pady=10)
        tk.Label(self.root, textvariable=app.status, bg=BG, fg=MUTED, font=(FONT, 9),
                 anchor="w", padx=13, pady=4).pack(side="bottom", fill="x")
        self.page.pack(fill="both", expand=True, padx=13)
        app.power.trace_add("write", self.refresh_power)
        self.refresh_power()
        self.show("CCT")

    def button(self, parent, title, command, **kwargs):
        options = dict(bg=BAR, fg=TEXT, activebackground=TILE, activeforeground=ACCENT,
                       relief="flat", bd=0, cursor="hand2", font=(FONT, 10), padx=7, pady=5)
        return tk.Button(parent, text=title, command=command, **(options | kwargs))

    def watch(self, variable, callback):
        self.traces.append((variable, variable.trace_add("write", lambda *_: callback())))

    def show(self, tab):
        if self.pending:
            self.root.after_cancel(self.pending)
            self.pending = None
        self.tab = tab
        for variable, handle in self.traces:
            variable.trace_remove("write", handle)
        self.traces.clear()
        for child in (*self.nav.winfo_children(), *self.page.winfo_children()):
            child.destroy()
        for column, (key, label) in enumerate((
            ("CCT", "白光"), ("TV", "光效"),
        )):
            selected = tab == key
            self.nav.columnconfigure(column, weight=1, uniform="tabs")
            self.button(self.nav, label, lambda k=key: self.show(k),
                        bg=TILE if selected else BG, fg=ACCENT if selected else "#777777",
                        pady=4).grid(row=0, column=column, sticky="ew", padx=3)
        {"CCT": self.white, "TV": self.effects}[tab]()

    def refresh_power(self, *_):
        self.power_button.configure(bg=ORANGE if self.app.power.get() else BAR)

    def toggle_power(self):
        if not self.app.client or (self.app.task and not self.app.task.done()):
            return
        self.app.power.set(not self.app.power.get())
        self.app.run(self.app.apply)

    def send(self):
        app = self.app
        if not app.client:
            return
        mode = self.tab
        if self.pending:
            self.root.after_cancel(self.pending)

        def deliver():
            self.pending = None
            if app.closing or not app.client:
                return
            if app.task and not app.task.done():
                self.pending = self.root.after(100, deliver)
                return
            app.mode.set(mode)
            app.run(app.apply)

        self.pending = self.root.after(100, deliver)

    def heading(self, text, variable, fmt):
        label = tk.Label(self.page, bg=BG, fg=TEXT, font=(FONT, 11))
        label.pack(pady=(6, 2))
        def refresh():
            label.configure(text=f"{text}  {fmt(variable.get())}")
        self.watch(variable, refresh)
        refresh()

    def slider(self, title, variable, lo, hi, fmt=str, step=1):
        self.heading(title, variable, fmt)
        row = tk.Frame(self.page, bg=BG)
        row.pack(fill="x", padx=3, pady=(0, 3))
        def set_value(value):
            variable.set(max(lo, min(hi, lo + round((value-lo)/step)*step)))
        def nudge(delta):
            set_value(variable.get() + delta)
            self.send()
        self.button(row, "⊖", lambda: nudge(-step), bg=BG, fg=MUTED, font=(FONT, 17),
                    padx=4, pady=0).pack(side="left")
        self.button(row, "⊕", lambda: nudge(step), bg=BG, fg=MUTED, font=(FONT, 17),
                    padx=4, pady=0).pack(side="right")
        canvas = tk.Canvas(row, bg=BG, height=31, bd=0, highlightthickness=0, cursor="hand2")
        canvas.pack(fill="x", expand=True, padx=13)
        def redraw(*_):
            w = max(17, canvas.winfo_width())
            x = 8 + (w-16)*max(0,min(1,(variable.get()-lo)/(hi-lo)))
            canvas.delete("all")
            canvas.create_line(8,16,w-8,16,fill=TEXT,width=4,capstyle="round")
            canvas.create_line(8,16,x,16,fill=ACCENT,width=5,capstyle="round")
            canvas.create_oval(x-7,9,x+7,23,fill=ACCENT,outline="")
        def move(event):
            set_value(lo+(hi-lo)*(event.x-8)/max(1,canvas.winfo_width()-16))
        canvas.bind("<Configure>", redraw)
        canvas.bind("<Button-1>", move)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", lambda event: (move(event), self.send()))
        self.watch(variable, redraw)

    def pills(self, variable, values, fmt, columns):
        grid = tk.Frame(self.page, bg=BG)
        grid.pack(fill="x", pady=(2, 6))
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="pills")
        for index, value in enumerate(values):
            pill = tk.Canvas(grid, bg=BG, height=44, bd=0, highlightthickness=0, cursor="hand2")
            pill.grid(row=index//columns, column=index%columns, sticky="ew", padx=4, pady=4)
            def paint(_, c=pill, v=value):
                w = max(c.winfo_width(), 48)
                color = ACCENT if variable.get() == v else MUTED
                c.delete("all")
                c.create_arc(3,3,41,41,start=90,extent=180,style="arc",outline=color)
                c.create_arc(w-41,3,w-3,41,start=-90,extent=180,style="arc",outline=color)
                c.create_line(22,3,w-22,3,fill=color)
                c.create_line(22,41,w-22,41,fill=color)
                c.create_text(w/2,22,text=fmt(v),fill=color,font=(FONT,10))
            pill.bind("<Configure>", paint)
            pill.bind("<Button-1>", lambda _, v=value: (variable.set(v), self.send()))
            self.watch(variable, lambda repaint=paint: repaint(None))

    def white(self):
        a = self.app
        self.slider("色温", a.kelvin, CCT_MIN, CCT_MAX, lambda n: f"{n}K", 100)
        self.pills(a.kelvin, (CCT_MIN, 3200, 4000, 5600, CCT_MAX), lambda n: f"{n}k", 5)
        self.slider("亮度", a.brightness, 0, 100, lambda n: f"{n}%")
        self.pills(a.brightness, (0,5,25,50,75,100), lambda n: f"{n}%", 3)

    def effects(self):
        a = self.app
        strip = tk.Frame(self.page, bg=BG)
        strip.pack(fill="x", pady=(6, 5))
        self.button(strip, "电视灯效", self.send, bg=ORANGE).pack()
        self.slider("亮度", a.brightness, 0, 100, lambda n: f"{n}%")
        self.slider("色温", a.kelvin, CCT_MIN, CCT_MAX, lambda n: f"{n}K", 100)
        self.slider("频率", a.rate, 0, 10)

    def settings(self):
        a = self.app
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        panel = self.settings_window = tk.Toplevel(self.root, bg=BG)
        panel.title("设置")
        panel.transient(self.root)
        panel.resizable(False, False)
        target = a.client.address if a.client else None
        index = a.device.current()
        if target:
            name = next((name for device, name in a.devices if device.address == target),
                        a.client.name or "ENSY-JS")
        elif 0 <= index < len(a.devices):
            device, name = a.devices[index]
            target = device.address
        else:
            tk.Label(panel, text="请先搜索并选择一盏灯具。", bg=BG, fg=TEXT,
                     font=(FONT, 10), padx=18, pady=18).pack()
            return

        address = target.upper()
        tk.Label(panel, text=f"设备别名 · {name}", bg=BG, fg=TEXT, font=(FONT, 11),
                 padx=16, pady=10).pack(anchor="w")
        alias = tk.StringVar(value=a.aliases.get(address, ""))
        entry = tk.Entry(panel, textvariable=alias, width=30, font=(FONT, 11))
        entry.pack(fill="x", padx=16)
        hint = tk.Label(panel, text="留空可恢复设备原名", bg=BG, fg=MUTED, font=(FONT, 9))
        hint.pack(anchor="w", padx=16, pady=5)

        def save():
            try:
                a.save_alias(address, name, alias.get())
            except (OSError, ValueError) as exc:
                hint.configure(text=str(exc))
            else:
                panel.destroy()

        self.button(panel, "保存", save, bg=ORANGE).pack(anchor="e", padx=16, pady=(3, 12))
        panel.bind("<Return>", lambda _: save())
        panel.bind("<Escape>", lambda _: panel.destroy())
        entry.focus_set()
