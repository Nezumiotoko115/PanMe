"""Freenove FNK0078向けPanMe Tkinter UI。"""

import queue
import tkinter as tk

import config
from locker_manager import DISABLED, ERROR, LOCKED, OPEN, UNLOCKED
from ui.controller import (
    AUTH,
    CLOSE_LOCKER,
    COMPLETE,
    ERROR_SCREEN,
    IDLE,
    LOCKER_CONFIRM,
    LOCKING,
    PRODUCT_DETAIL,
    PRODUCT_LIST,
    TAKE_PRODUCT,
    UNLOCKED_SCREEN,
    UNLOCKING,
    WELCOME,
    PanMeController,
)


class PanMeUI:
    """画面表示だけを担当し、ロッカー制御はControllerへ依頼します。"""

    CATEGORY_COLORS = {
        "パン": "#F7C873",
        "おにぎり": "#94C9A9",
        "サンドイッチ": "#F3A683",
        "飲料": "#82BFE0",
        "お菓子": "#D8A7D8",
    }

    def __init__(
        self,
        root,
        locker_manager,
        authentication_service,
        product_service,
        event_logger,
    ):
        self.root = root
        self.root.title(config.UI_TITLE)
        self.root.configure(bg=config.UI_BACKGROUND)
        self.root.attributes("-fullscreen", config.FULLSCREEN)
        self.root.minsize(800, 480)
        self.root.bind("<Escape>", lambda _event: self._leave_fullscreen())
        self.root.bind("<F11>", lambda _event: self._toggle_fullscreen())
        self.root.bind("<Button-1>", self._user_activity, add="+")
        self.root.bind("<Button-3>", self._demo_right_click, add="+")

        self._ui_callbacks = queue.Queue()
        self._timeout_job = None
        self._screen_job = None
        self._loading_job = None
        self._loading_step = 0

        self.controller = PanMeController(
            locker_manager,
            authentication_service,
            product_service,
            event_logger,
            schedule=self._post_from_worker,
        )
        self.controller.on_change = self.render

        self.container = tk.Frame(root, bg=config.UI_BACKGROUND)
        self.container.pack(fill="both", expand=True)
        self.root.after(50, self._poll_worker_callbacks)
        self.root.after(100, self.controller.start)

    def _post_from_worker(self, _delay_ms, callback):
        """ハードウェアスレッドからUI用キューへ結果を渡します。"""
        self._ui_callbacks.put(callback)

    def _poll_worker_callbacks(self):
        try:
            while True:
                self._ui_callbacks.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(50, self._poll_worker_callbacks)

    def _leave_fullscreen(self):
        self.root.attributes("-fullscreen", False)

    def _toggle_fullscreen(self):
        self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))

    def _user_activity(self, _event=None):
        self._reset_timeout()
        # 待機画面は、ボタン以外の場所を含む画面全体をタッチできます。
        if self.controller.state == IDLE:
            self.controller.begin()
        elif self.controller.state == AUTH and not config.DEMO_MODE:
            self.controller.authenticate()

    def _reset_timeout(self):
        if self._timeout_job:
            self.root.after_cancel(self._timeout_job)
        self._timeout_job = self.root.after(
            int(config.SCREEN_TIMEOUT * 1000),
            self._on_timeout,
        )

    def _on_timeout(self):
        self.controller.handle_timeout()
        self._reset_timeout()

    def _demo_right_click(self, _event=None):
        """撮影用バックアップ。DEMO_MODEの待機・認証画面だけで有効です。"""
        if not config.DEMO_MODE:
            return
        if self.controller.state == IDLE:
            self.controller.begin()
        elif self.controller.state == AUTH and not config.DEMO_MODE:
            self.controller.authenticate()

    def _cancel_jobs(self):
        for attribute in ("_screen_job", "_loading_job"):
            job = getattr(self, attribute)
            if job:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)

    def _clear(self):
        self._cancel_jobs()
        for child in self.container.winfo_children():
            child.destroy()

    def _scale(self):
        """現在の画面サイズから、横長画面向けの基準倍率を求めます。"""
        width = max(self.root.winfo_width(), self.root.winfo_screenwidth())
        height = max(self.root.winfo_height(), self.root.winfo_screenheight())
        return max(0.75, min(1.35, min(width / 1024, height / 600)))

    def _font(self, size, weight="normal"):
        return (config.UI_FONT_FAMILY, max(10, int(size * self._scale())), weight)

    def _button(self, parent, text, command, primary=True, **options):
        colors = (
            (config.UI_PRIMARY, "#FFFFFF", "#D9572B")
            if primary
            else ("#FFFFFF", config.UI_TEXT, "#F2E8DA")
        )
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=self._font(18, "bold"),
            bg=colors[0],
            fg=colors[1],
            activebackground=colors[2],
            activeforeground=colors[1],
            relief="flat",
            bd=0,
            padx=int(24 * self._scale()),
            pady=int(13 * self._scale()),
            cursor="hand2",
            **options,
        )

    def _header(self, title, show_back=False):
        header = tk.Frame(self.container, bg="#FFFFFF", height=int(72 * self._scale()))
        header.pack(fill="x")
        header.pack_propagate(False)

        left = tk.Frame(header, bg="#FFFFFF")
        left.pack(side="left", padx=22)
        if show_back:
            self._button(left, "← 戻る", self.controller.back, primary=False).pack(
                side="left", padx=(0, 16)
            )
        tk.Label(
            left,
            text="PanMe",
            font=self._font(25, "bold"),
            fg=config.UI_PRIMARY,
            bg="#FFFFFF",
        ).pack(side="left")
        tk.Label(
            left,
            text=title,
            font=self._font(17, "bold"),
            fg=config.UI_TEXT,
            bg="#FFFFFF",
        ).pack(side="left", padx=22)

        machine_text, machine_color = self._machine_status()
        tk.Label(
            header,
            text=f"● 販売機は{machine_text}",
            font=self._font(12, "bold"),
            fg=machine_color,
            bg="#FFFFFF",
        ).pack(side="right", padx=24)
        return header

    def _machine_status(self):
        system_status = getattr(self.controller.locker_manager, "system_status", None)
        if system_status and system_status() != "ONLINE":
            return "サーバーと通信できません", "#B42318"
        states = self.controller.locker_manager.get_all_locker_status().values()
        if any(state in (ERROR, DISABLED) for state in states):
            return "一部利用不可です", "#A66A00"
        return "正常に稼働しています", "#278252"

    def _center(self):
        frame = tk.Frame(self.container, bg=config.UI_BACKGROUND)
        frame.pack(fill="both", expand=True)
        inner = tk.Frame(frame, bg=config.UI_BACKGROUND)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        return inner

    def render(self, _controller=None):
        self._clear()
        self._reset_timeout()
        renderer = {
            IDLE: self._idle_screen,
            AUTH: self._auth_screen,
            WELCOME: self._welcome_screen,
            PRODUCT_LIST: self._product_list_screen,
            PRODUCT_DETAIL: self._product_detail_screen,
            LOCKER_CONFIRM: self._confirm_screen,
            UNLOCKING: lambda: self._loading_screen("ロッカーを開けています", "しばらくお待ちください"),
            UNLOCKED_SCREEN: self._unlocked_screen,
            TAKE_PRODUCT: self._take_product_screen,
            CLOSE_LOCKER: self._close_locker_screen,
            LOCKING: lambda: self._loading_screen("ロッカーを施錠しています", "安全を確認しています"),
            COMPLETE: self._complete_screen,
            ERROR_SCREEN: self._error_screen,
        }[self.controller.state]
        renderer()

    def _idle_screen(self):
        outer = tk.Frame(self.container, bg=config.UI_PRIMARY)
        outer.pack(fill="both", expand=True)
        center = tk.Frame(outer, bg=config.UI_PRIMARY)
        center.place(relx=0.5, rely=0.46, anchor="center")
        for widget in (
            tk.Label(center, text="PanMe", font=self._font(68, "bold"), fg="#FFFFFF", bg=config.UI_PRIMARY),
            tk.Label(center, text="高校の毎日に、ちょっと便利を。", font=self._font(24, "bold"), fg="#FFF3D6", bg=config.UI_PRIMARY),
            tk.Label(center, text="画面をタッチしてスタート", font=self._font(27, "bold"), fg="#FFFFFF", bg=config.UI_PRIMARY, pady=35),
        ):
            widget.pack()
        tk.Label(
            outer,
            text="DEMO MODE",
            font=self._font(11),
            fg="#FFE6D9",
            bg=config.UI_PRIMARY,
        ).pack(side="bottom", pady=20)

    def _auth_screen(self):
        self._header("認証")
        center = self._center()
        tk.Label(
            center,
            text="カードをタッチしてください",
            font=self._font(32, "bold"),
            fg=config.UI_TEXT, bg=config.UI_BACKGROUND,
        ).pack(pady=12)
        tk.Label(
            center,
            text="認証しています。しばらくお待ちください",
            font=self._font(17), fg=config.UI_MUTED, bg=config.UI_BACKGROUND,
        ).pack(pady=8)
        if config.DEMO_MODE:
            tk.Label(
                center,
                text="",
                font=self._font(15),
                fg=config.UI_SECONDARY,
                bg=config.UI_BACKGROUND,
            ).pack(pady=20)
            self._screen_job = self.root.after(
                int(config.DEMO_AUTH_SECONDS * 1000),
                lambda: self.controller.authenticate()
                if self.controller.state == AUTH else None,
            )
        else:
            tk.Label(
                center,
                text="カードをタッチしてください",
                font=self._font(18),
                fg=config.UI_SECONDARY,
                bg=config.UI_BACKGROUND,
            ).pack(pady=20)

    def _welcome_screen(self):
        self._header("ようこそ")
        center = self._center()
        name = self.controller.user["user_name"]
        tk.Label(
            center, text=f"{name}さん", font=self._font(42, "bold"),
            fg=config.UI_SECONDARY, bg=config.UI_BACKGROUND,
        ).pack()
        tk.Label(
            center, text="ようこそ！", font=self._font(48, "bold"),
            fg=config.UI_PRIMARY, bg=config.UI_BACKGROUND,
        ).pack(pady=8)
        tk.Label(
            center, text="PanMeの商品を選んでください",
            font=self._font(20), fg=config.UI_TEXT, bg=config.UI_BACKGROUND,
        ).pack(pady=18)
        self._button(center, "商品を見る", self.controller.show_products).pack(pady=10)
        self._screen_job = self.root.after(
            int(config.WELCOME_DISPLAY_SECONDS * 1000),
            lambda: self.controller.show_products()
            if self.controller.state == WELCOME else None,
        )

    def _product_list_screen(self):
        self._header("商品を選んでください", show_back=True)
        grid = tk.Frame(self.container, bg=config.UI_BACKGROUND)
        grid.pack(fill="both", expand=True, padx=14, pady=12)
        for index in range(4):
            grid.grid_columnconfigure(index, weight=1, uniform="product")
            grid.grid_rowconfigure(index, weight=1, uniform="product")

        products = self.controller.products()
        if not products:
            tk.Label(
                grid,
                text="現在、商品情報を取得できません。\n通信状態を確認して、もう一度お試しください。",
                font=self._font(22, "bold"),
                fg=config.UI_ERROR,
                bg=config.UI_BACKGROUND,
            ).grid(row=0, column=0, rowspan=4, columnspan=4)
            return

        for index, product in enumerate(products):
            row, column = divmod(index, 4)
            available, availability = self.controller.product_availability(product)
            card_color = self.CATEGORY_COLORS.get(product["category"], config.UI_CARD)
            if not available:
                card_color = "#E5E5E5"
            stock_text = (
                "売り切れ"
                if product["stock"] == 0
                else f"残り {product['stock']}個"
            )
            if product["stock"] in (1, 2):
                stock_text += "・残りわずか"
            text = (
                f"{product['locker_id']}  |  {product['category']}\n"
                f"{product['product_name']}\n"
                f"{stock_text}\n{availability}"
            )
            button = tk.Button(
                grid,
                text=text,
                command=lambda item=product: self.controller.select_product(item),
                state="normal" if available else "disabled",
                disabledforeground="#777777",
                font=self._font(12, "bold"),
                bg=card_color,
                fg=config.UI_TEXT,
                activebackground=config.UI_ACCENT,
                relief="flat",
                bd=0,
                padx=6,
                pady=5,
                wraplength=int(205 * self._scale()),
                cursor="hand2",
            )
            button.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)

    def _product_visual(self, parent, product):
        color = self.CATEGORY_COLORS.get(product["category"], config.UI_ACCENT)
        scale = self._scale()
        visual = tk.Canvas(
            parent, width=int(260 * scale), height=int(210 * scale),
            bg=color, highlightthickness=0,
        )
        visual.create_oval(
            int(55 * scale), int(30 * scale), int(205 * scale), int(180 * scale),
            fill="#FFFFFF", outline="",
        )
        visual.create_text(
            int(130 * scale), int(105 * scale), text=product["category"],
            font=self._font(22, "bold"), fill=config.UI_TEXT,
        )
        visual.pack(side="left", padx=30)

    def _product_detail_screen(self):
        product = self.controller.selected_product
        self._header("商品詳細", show_back=True)
        content = tk.Frame(self.container, bg=config.UI_BACKGROUND)
        content.pack(fill="both", expand=True, padx=45, pady=30)
        self._product_visual(content, product)
        info = tk.Frame(content, bg=config.UI_BACKGROUND)
        info.pack(side="left", fill="both", expand=True, padx=35)
        tk.Label(info, text=product["product_name"], font=self._font(36, "bold"),
                 fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack(anchor="w", pady=8)
        tk.Label(info, text=f"ロッカー {product['locker_id']}", font=self._font(22, "bold"),
                 fg=config.UI_SECONDARY, bg=config.UI_BACKGROUND).pack(anchor="w", pady=7)
        tk.Label(info, text=f"在庫：残り {product['stock']}個", font=self._font(19),
                 fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack(anchor="w", pady=7)
        self._button(info, "この商品を利用する", self.controller.confirm_product).pack(
            anchor="w", pady=28
        )

    def _confirm_screen(self):
        product = self.controller.selected_product
        self._header("ロッカー確認", show_back=True)
        center = self._center()
        tk.Label(center, text=product["product_name"], font=self._font(34, "bold"),
                 fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack()
        tk.Label(center, text=f"ロッカー {product['locker_id']}", font=self._font(42, "bold"),
                 fg=config.UI_PRIMARY, bg=config.UI_BACKGROUND).pack(pady=18)
        tk.Label(center, text="このロッカーを開けます。よろしいですか？",
                 font=self._font(20), fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack(pady=10)
        self._button(center, "ロッカーを開ける", self.controller.unlock).pack(pady=25)

    def _loading_screen(self, title, subtitle):
        self._header("処理中")
        center = self._center()
        title_label = tk.Label(
            center, text=title, font=self._font(34, "bold"),
            fg=config.UI_PRIMARY, bg=config.UI_BACKGROUND,
        )
        title_label.pack(pady=15)
        tk.Label(center, text=subtitle, font=self._font(18),
                 fg=config.UI_MUTED, bg=config.UI_BACKGROUND).pack()
        dots = tk.Label(center, text="● ○ ○", font=self._font(24, "bold"),
                        fg=config.UI_SECONDARY, bg=config.UI_BACKGROUND)
        dots.pack(pady=30)

        def animate():
            patterns = ("● ○ ○", "○ ● ○", "○ ○ ●")
            dots.configure(text=patterns[self._loading_step % 3])
            self._loading_step += 1
            self._loading_job = self.root.after(350, animate)

        animate()

    def _unlocked_screen(self):
        product = self.controller.selected_product
        self._header("解錠完了")
        center = self._center()
        tk.Label(center, text="ロッカーが開きました！", font=self._font(40, "bold"),
                 fg="#278252", bg=config.UI_BACKGROUND).pack()
        tk.Label(center, text=product["locker_id"], font=self._font(58, "bold"),
                 fg=config.UI_PRIMARY, bg=config.UI_BACKGROUND).pack(pady=12)
        tk.Label(center, text=f"{product['product_name']}をお取りください",
                 font=self._font(22), fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack(pady=8)
        self._button(center, "商品を取り出す", self.controller.continue_to_take_product).pack(pady=24)

    def _take_product_screen(self):
        product = self.controller.selected_product
        self._header("商品受取")
        center = self._center()
        tk.Label(center, text="商品を取り出してください", font=self._font(36, "bold"),
                 fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack()
        tk.Label(center, text=f"{product['locker_id']}  •  {product['product_name']}",
                 font=self._font(22), fg=config.UI_SECONDARY, bg=config.UI_BACKGROUND).pack(pady=20)
        self._button(center, "商品を受け取りました", self.controller.product_received).pack(pady=25)

    def _close_locker_screen(self):
        self._header("扉を閉める")
        center = self._center()
        tk.Label(center, text="ロッカーを閉じてください", font=self._font(38, "bold"),
                 fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack()
        tk.Label(center, text=self.controller.selected_product["locker_id"],
                 font=self._font(54, "bold"), fg=config.UI_PRIMARY,
                 bg=config.UI_BACKGROUND).pack(pady=18)
        tk.Label(center, text="指や商品を挟まないようご注意ください",
                 font=self._font(18), fg=config.UI_ERROR, bg=config.UI_BACKGROUND).pack(pady=8)
        self._button(center, "ロッカーを閉じました", self.controller.close_and_lock).pack(pady=24)

    def _complete_screen(self):
        self._header("利用完了")
        center = self._center()
        tk.Label(center, text="ご利用ありがとうございました！", font=self._font(40, "bold"),
                 fg=config.UI_PRIMARY, bg=config.UI_BACKGROUND).pack()
        tk.Label(center, text="またPanMeをご利用ください",
                 font=self._font(23), fg=config.UI_TEXT, bg=config.UI_BACKGROUND).pack(pady=20)
        tk.Label(center, text="まもなく最初の画面へ戻ります",
                 font=self._font(14), fg=config.UI_MUTED, bg=config.UI_BACKGROUND).pack(pady=8)
        self._screen_job = self.root.after(
            int(config.COMPLETE_DISPLAY_SECONDS * 1000),
            self.controller.cancel_to_idle,
        )

    def _error_screen(self):
        self._header("お知らせ")
        center = self._center()
        tk.Label(center, text="申し訳ありません", font=self._font(38, "bold"),
                 fg=config.UI_ERROR, bg=config.UI_BACKGROUND).pack()
        tk.Label(center, text="ロッカーを操作できませんでした",
                 font=self._font(25, "bold"), fg=config.UI_TEXT,
                 bg=config.UI_BACKGROUND).pack(pady=18)
        tk.Label(center, text="係員にお知らせください",
                 font=self._font(18), fg=config.UI_MUTED,
                 bg=config.UI_BACKGROUND).pack(pady=6)
        self._button(center, "最初に戻る", self.controller.cancel_to_idle).pack(pady=28)
