"""Ana pencere ve uygulama giriş noktası."""

import json
import sys
import threading
import webbrowser
from tkinter import messagebox, ttk

import customtkinter as ctk

from cs2_picker.core.config import APP_NAME, APP_VERSION, SETTINGS_FILE, SUPPORT_DIR
from cs2_picker.core.constants import GITHUB_RELEASES_URL, UPDATE_CHECK_INTERVAL_MS
from cs2_picker.services.firewall import (
    block_all,
    block_regions,
    is_blocked,
    load_blocked,
    unblock_all,
    unblock_regions,
)
from cs2_picker.services.ping import ping_server
from cs2_picker.services.server import fetch_server_data, get_server_dict
from cs2_picker.services.update import (
    ReleaseInfo,
    apply_update,
    can_self_update,
    check_for_update,
)


class MainWindow(ctk.CTk):
    C = {
        "bg": "#141417",
        "panel": "#1c1c21",
        "card": "#232329",
        "border": "#2f2f38",
        "text": "#ececee",
        "muted": "#9494a0",
        "accent": "#2383e2",
        "accent_h": "#1a6fc4",
        "block": "#e5484d",
        "block_h": "#c93d42",
        "block_soft": "#4a2828",
        "unblock": "#30a46c",
        "unblock_h": "#278a59",
        "unblock_soft": "#1e3d2e",
        "warn": "#f5a623",
        "row_sel": "#2383e2",
    }

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("980x680")
        self.minsize(860, 580)
        self.configure(fg_color=self.C["bg"])

        self.clustered: dict[str, str] = {}
        self.unclustered: dict[str, str] = {}
        self.is_clustered = False
        self.server_revision = ""
        self.pending = False
        self._ping_cancel = threading.Event()
        self._pending_release: ReleaseInfo | None = None
        self._update_busy = False

        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        self._load_settings()
        self._build_ui()
        self.after(100, self._bootstrap)
        self.after(3000, self._check_updates_async)
        self._schedule_update_checks()

    def _load_settings(self) -> None:
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text())
                self.is_clustered = bool(data.get("is_clustered", False))
                self.server_revision = str(data.get("server_revision", ""))
            except (json.JSONDecodeError, OSError):
                pass

    def _save_settings(self) -> None:
        SETTINGS_FILE.write_text(
            json.dumps(
                {"is_clustered": self.is_clustered, "server_revision": self.server_revision},
                indent=2,
            )
        )

    def _server_dict(self) -> dict[str, str]:
        return get_server_dict(self.is_clustered, self.clustered, self.unclustered)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, fg_color=self.C["panel"], corner_radius=0, width=200)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar,
            text="CS2",
            font=ctk.CTkFont(size=36, weight="bold"),
            text_color=self.C["accent"],
        ).pack(pady=(28, 0))
        ctk.CTkLabel(
            sidebar,
            text="Server Picker",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.C["text"],
        ).pack(pady=(0, 4))
        ctk.CTkLabel(
            sidebar,
            text=f"v{APP_VERSION} · macOS",
            font=ctk.CTkFont(size=11),
            text_color=self.C["muted"],
        ).pack(pady=(0, 24))

        ctk.CTkButton(
            sidebar,
            text="GitHub",
            height=32,
            corner_radius=8,
            fg_color=self.C["border"],
            hover_color=self.C["accent_h"],
            command=lambda: webbrowser.open(GITHUB_RELEASES_URL),
        ).pack(fill="x", padx=16, pady=4)

        self.update_btn = ctk.CTkButton(
            sidebar,
            text="Güncelle",
            height=34,
            corner_radius=8,
            fg_color=self.C["warn"],
            hover_color="#d4921f",
            text_color="#1a1a1e",
            command=self._on_apply_update,
        )

        ctk.CTkButton(
            sidebar,
            text="Refresh",
            height=36,
            corner_radius=8,
            fg_color=self.C["accent"],
            hover_color=self.C["accent_h"],
            command=self._on_refresh_ping,
        ).pack(fill="x", padx=16, pady=(20, 4))

        self.cluster_btn = ctk.CTkButton(
            sidebar,
            text="Cluster",
            height=32,
            corner_radius=8,
            fg_color=self.C["border"],
            hover_color="#3a3a44",
            command=self._on_toggle_cluster,
        )
        self.cluster_btn.pack(fill="x", padx=16, pady=4)

        ctk.CTkButton(
            sidebar,
            text="Info",
            height=32,
            corner_radius=8,
            fg_color=self.C["border"],
            hover_color="#3a3a44",
            command=self._on_info,
        ).pack(fill="x", padx=16, pady=4)

        ctk.CTkFrame(sidebar, fg_color="transparent", height=1).pack(expand=True)

        ctk.CTkLabel(
            sidebar,
            text="pf firewall\nadmin gerekir",
            font=ctk.CTkFont(size=10),
            text_color=self.C["muted"],
            justify="center",
        ).pack(pady=16)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(main, fg_color=self.C["card"], corner_radius=12, height=52)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top,
            text="Steam Datagram Relay Sunucuları",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=self.C["text"],
        ).grid(row=0, column=0, padx=16, pady=14, sticky="w")

        self.status_label = ctk.CTkLabel(
            top,
            text="Hazırlanıyor…",
            font=ctk.CTkFont(size=12),
            text_color=self.C["muted"],
        )
        self.status_label.grid(row=0, column=1, padx=8, pady=14, sticky="e")

        self.progress = ctk.CTkProgressBar(top, width=100, mode="indeterminate")
        self.progress.grid(row=0, column=2, padx=(0, 16), pady=14, sticky="e")
        self.progress.grid_remove()

        table_wrap = ctk.CTkFrame(main, fg_color=self.C["card"], corner_radius=12)
        table_wrap.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "CS2.Treeview",
            background=self.C["bg"],
            foreground=self.C["text"],
            fieldbackground=self.C["bg"],
            borderwidth=0,
            rowheight=34,
            font=("SF Pro Text", 13),
        )
        style.configure(
            "CS2.Treeview.Heading",
            background=self.C["panel"],
            foreground=self.C["muted"],
            borderwidth=0,
            font=("SF Pro Text", 12, "bold"),
        )
        style.map(
            "CS2.Treeview",
            background=[("selected", self.C["row_sel"])],
            foreground=[("selected", "#ffffff")],
        )

        cols = ("server", "latency")
        self.tree = ttk.Treeview(
            table_wrap,
            columns=cols,
            show="headings",
            selectmode="extended",
            style="CS2.Treeview",
        )
        self.tree.heading("server", text="Servers")
        self.tree.heading("latency", text="Latency")
        self.tree.column("server", width=560, anchor="w", stretch=True)
        self.tree.column("latency", width=140, anchor="center", stretch=False)

        scroll = ctk.CTkScrollbar(table_wrap, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(14, 0), pady=14)
        scroll.grid(row=0, column=1, sticky="ns", padx=(6, 14), pady=14)
        self.tree.bind("<Double-1>", lambda _: self._on_refresh_selected_ping())

        actions = ctk.CTkFrame(main, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew")
        for i in range(4):
            actions.grid_columnconfigure(i, weight=1)

        self._action_btn(
            actions, "Block Selected", self._on_block_selected,
            0, fg=self.C["block_soft"], hover=self.C["block_h"], text_color="#ffb4b4",
        )
        self._action_btn(
            actions, "Block All", self._on_block_all,
            1, fg=self.C["block"], hover=self.C["block_h"],
        )
        self._action_btn(
            actions, "Unblock All", self._on_unblock_all,
            2, fg=self.C["unblock"], hover=self.C["unblock_h"],
        )
        self._action_btn(
            actions, "Unblock Selected", self._on_unblock_selected,
            3, fg=self.C["unblock_soft"], hover=self.C["unblock_h"], text_color="#b8f0d0",
        )

    def _action_btn(self, parent, text, cmd, col, fg, hover, text_color="#ffffff"):
        ctk.CTkButton(
            parent,
            text=text,
            command=cmd,
            height=50,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=fg,
            hover_color=hover,
            text_color=text_color,
        ).grid(row=0, column=col, padx=(0 if col == 0 else 6, 0), sticky="ew")

    def _set_pending(self, active: bool, msg: str = "") -> None:
        self.pending = active
        if active:
            self.progress.grid()
            self.progress.start()
            self.status_label.configure(text=msg or "İşlem sürüyor…")
        else:
            self.progress.stop()
            self.progress.grid_remove()
            count = len(self._server_dict())
            self.status_label.configure(text=msg or f"{count} sunucu · hazır")

    def _bootstrap(self) -> None:
        self._set_pending(True, "Sunucu listesi alınıyor…")

        def work():
            try:
                rev, clustered, unclustered = fetch_server_data()
                self.after(0, lambda: self._on_data_loaded(rev, clustered, unclustered, None))
            except Exception as exc:
                self.after(0, lambda: self._on_data_loaded("", {}, {}, exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_data_loaded(self, revision, clustered, unclustered, error) -> None:
        if error:
            self._set_pending(False, "Veri alınamadı")
            messagebox.showerror("Hata", f"Sunucu verisi alınamadı:\n{error}")
            return

        self.clustered = clustered
        self.unclustered = unclustered

        if self.server_revision and self.server_revision != revision:
            messagebox.showinfo(
                "Güncelleme",
                "Valve sunucu verisini güncelledi.\nEngellenen sunucular sıfırlanacak.",
            )
            self._run_async(lambda: unblock_all(self._server_dict()), self._reload_list)
            self.server_revision = revision
            self._save_settings()
            return

        self.server_revision = revision
        self._save_settings()
        self._reload_list()
        self.cluster_btn.configure(text="Uncluster" if self.is_clustered else "Cluster")
        self._set_pending(False)
        self._ping_all_async()

    def _reload_list(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for region in sorted(self._server_dict().keys()):
            self.tree.insert("", "end", iid=region, values=(region, "—"))

    def _selected_regions(self) -> list[str]:
        return list(self.tree.selection())

    def _run_async(self, fn, on_done=None) -> None:
        if self.pending:
            messagebox.showwarning("Bekle", "Devam eden işlem var.")
            return
        self._set_pending(True)

        def work():
            try:
                result = fn()
                self.after(0, lambda: self._async_done(result, None, on_done))
            except Exception as exc:
                self.after(0, lambda: self._async_done(None, exc, on_done))

        threading.Thread(target=work, daemon=True).start()

    def _async_done(self, result, error, on_done) -> None:
        self._set_pending(False)
        if error:
            messagebox.showerror("Hata", str(error))
            return
        if result and isinstance(result, tuple) and not result[0]:
            messagebox.showerror("Firewall Hatası", result[1])
            return
        if on_done:
            on_done()

    def _on_block_selected(self) -> None:
        regions = self._selected_regions()
        if not regions:
            messagebox.showinfo("Bilgi", "Sunucu seçmedin.")
            return
        sd = self._server_dict()
        self._run_async(
            lambda: block_regions(regions, sd),
            lambda: (self._reload_list(), self._ping_selected_async()),
        )

    def _on_unblock_selected(self) -> None:
        regions = self._selected_regions()
        if not regions:
            messagebox.showinfo("Bilgi", "Sunucu seçmedin.")
            return
        sd = self._server_dict()
        self._run_async(
            lambda: unblock_regions(regions, sd),
            lambda: (self._reload_list(), self._ping_selected_async()),
        )

    def _on_block_all(self) -> None:
        sd = self._server_dict()
        self._run_async(lambda: block_all(sd), lambda: (self._reload_list(), self._ping_all_async()))

    def _on_unblock_all(self) -> None:
        sd = self._server_dict()
        self._run_async(lambda: unblock_all(sd), lambda: (self._reload_list(), self._ping_all_async()))

    def _on_toggle_cluster(self) -> None:
        if self.pending:
            messagebox.showwarning("Bekle", "Devam eden işlem var.")
            return

        def after_unblock():
            self.is_clustered = not self.is_clustered
            self.cluster_btn.configure(text="Uncluster" if self.is_clustered else "Cluster")
            self._save_settings()
            self._reload_list()
            self._ping_all_async()

        self._run_async(lambda: unblock_all(self._server_dict()), after_unblock)

    def _on_refresh_ping(self) -> None:
        self._ping_all_async()

    def _on_refresh_selected_ping(self) -> None:
        self._ping_selected_async()

    def _update_row_ping(self, region: str, text: str, status: str) -> None:
        try:
            self.tree.set(region, "latency", text)
            if status == "blocked":
                self.tree.item(region, tags=("blocked",))
            elif status == "ok":
                self.tree.item(region, tags=("ok",))
            elif status == "timeout":
                self.tree.item(region, tags=("timeout",))
        except Exception:
            pass

        self.tree.tag_configure("blocked", foreground="#ff8080")
        self.tree.tag_configure("ok", foreground="#6ee7a0")
        self.tree.tag_configure("timeout", foreground="#f5a623")

    def _ping_all_async(self) -> None:
        self._ping_cancel.set()
        self._ping_cancel = threading.Event()
        cancel = self._ping_cancel
        sd = self._server_dict()

        def work():
            for region in sd:
                if cancel.is_set():
                    return
                self.after(0, lambda r=region: self._update_row_ping(r, "…", "ok"))
                text, status = ping_server(sd[region], is_blocked(region))
                if cancel.is_set():
                    return
                self.after(0, lambda r=region, t=text, s=status: self._update_row_ping(r, t, s))

        threading.Thread(target=work, daemon=True).start()

    def _ping_selected_async(self) -> None:
        regions = self._selected_regions()
        if not regions:
            return
        sd = self._server_dict()

        def work():
            for region in regions:
                if region not in sd:
                    continue
                text, status = ping_server(sd[region], is_blocked(region))
                self.after(0, lambda r=region, t=text, s=status: self._update_row_ping(r, t, s))

        threading.Thread(target=work, daemon=True).start()

    def _on_info(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            "Nasıl kullanılır:\n"
            "• Cmd/Ctrl + tık ile çoklu seçim\n"
            "• Çift tık ile seçili sunuculara ping\n"
            "• Engelleme macOS pf firewall kullanır\n"
            "• Admin şifresi istenir\n"
            "• Güncellemeler GitHub Releases'tan kontrol edilir\n\n"
            f"Sürüm: {APP_VERSION}",
        )

    def _schedule_update_checks(self) -> None:
        self.after(UPDATE_CHECK_INTERVAL_MS, self._on_update_timer)

    def _on_update_timer(self) -> None:
        self._check_updates_async()
        self._schedule_update_checks()

    def _check_updates_async(self) -> None:
        if self._update_busy:
            return

        def work():
            release = check_for_update(APP_VERSION)
            self.after(0, lambda: self._set_update_available(release))

        threading.Thread(target=work, daemon=True).start()

    def _set_update_available(self, release: ReleaseInfo | None) -> None:
        if release is None:
            return
        if self._pending_release and self._pending_release.version == release.version:
            return

        self._pending_release = release
        self.update_btn.configure(text=f"Güncelle v{release.version}")
        if not self.update_btn.winfo_ismapped():
            self.update_btn.pack(fill="x", padx=16, pady=(8, 4), before=self.cluster_btn)

    def _on_apply_update(self) -> None:
        if not self._pending_release or self._update_busy:
            return

        release = self._pending_release
        if not messagebox.askyesno(
            "Güncelleme",
            f"Yeni sürüm v{release.version} mevcut.\n\n"
            f"Mevcut: v{APP_VERSION}\n\n"
            "Güncellemek istiyor musun?",
        ):
            return

        if not can_self_update():
            webbrowser.open(release.html_url)
            messagebox.showinfo(
                "Güncelleme",
                "Geliştirme modunda otomatik kurulum yok.\nRelease sayfası tarayıcıda açıldı.",
            )
            return

        self._update_busy = True
        self.update_btn.configure(state="disabled")
        self.status_label.configure(text=f"v{release.version} indiriliyor…")

        def work():
            try:
                def on_progress(done: int, total: int) -> None:
                    pct = min(100, int(done * 100 / max(total, 1)))
                    self.after(
                        0,
                        lambda p=pct: self.status_label.configure(
                            text=f"Güncelleme indiriliyor… %{p}"
                        ),
                    )

                apply_update(release, progress=on_progress)
                self.after(0, self.destroy)
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Güncelleme hatası", str(exc)))
                self.after(0, self._reset_update_ui)

        threading.Thread(target=work, daemon=True).start()

    def _reset_update_ui(self) -> None:
        self._update_busy = False
        self.update_btn.configure(state="normal")
        count = len(self._server_dict())
        self.status_label.configure(text=f"{count} sunucu · hazır")


def main() -> None:
    if sys.platform != "darwin":
        messagebox.showwarning("Platform", "Bu uygulama macOS için tasarlandı.")
    app = MainWindow()
    app.mainloop()
