import os, json, time, math, random, threading
import tkinter as tk
from collections import deque
from PIL import Image, ImageTk, ImageDraw
import sys
from pathlib import Path

# ──────── Auto-start registry (Windows only) ────────
try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "J.A.R.V.I.S"

# ──────── Color palette ────────
C_BG     = "#000000"
C_PRI    = "#00d4ff"
C_MID    = "#007a99"
C_DIM    = "#003344"
C_DIMMER = "#001520"
C_ACC    = "#ff6600"
C_ACC2   = "#ffcc00"
C_TEXT   = "#8ffcff"
C_PANEL  = "#010c10"
C_GREEN  = "#00ff88"
C_RED    = "#ff3333"
C_AMBER  = "#ff9500"
C_HEADER = "#00080d"


class JarvisUI:
    def __init__(self, face_path=None, size=None):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.resizable(False, False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 984)
        H  = min(sh, 816)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.root.configure(bg=C_BG)

        self.W = W
        self.H = H

        self.FACE_SZ = min(int(H * 0.54), 400)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.13) + self.FACE_SZ // 2

        # ── Animation state ──
        self.speaking     = False
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.tick         = 0
        self.scan_angle   = 0.0
        self.scan2_angle  = 180.0
        self.rings_spin   = [0.0, 120.0, 240.0]
        self.pulse_r      = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text  = "INITIALISING"
        self.status_blink = True
        self._start_time  = time.time()

        # ── Orbiting particles ──
        self._particles = []
        for _ in range(12):
            self._particles.append({
                "angle": random.uniform(0, 360),
                "r": random.uniform(self.FACE_SZ * 0.42, self.FACE_SZ * 0.58),
                "speed": random.uniform(0.3, 1.2),
                "size": random.randint(1, 3),
                "alpha": random.randint(60, 180),
            })

        # ── Connection state ──
        self.conn_state    = "CONNECTING"
        self._anim_rgb     = (0, 212, 255)

        # ── Audio visualizer state ──
        self.mic_level     = 0.0
        self.jarvis_level  = 0.0
        self._mic_bars     = [0.0] * 40
        self._jarvis_bars  = [0.0] * 28
        self._jarvis_shockwaves = []
        self._mic_shockwaves    = []

        # ── Typing / log ──
        self.typing_queue = deque()
        self.is_typing    = False

        # ── Face image ──
        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._load_face(face_path)

        # ── Canvas ──
        self.bg = tk.Canvas(self.root, width=W, height=H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)

        # ── Canvas interaction ──
        self._close_btn_rect    = None
        self._settings_btn_rect = None
        self._hover_close       = False
        self._hover_settings    = False
        self._settings_open     = False
        self._settings_frame    = None
        self.bg.bind("<Button-1>", self._on_canvas_click)
        self.bg.bind("<Motion>", self._on_canvas_motion)

        # ── Log panel ──
        LW = int(W * 0.72)
        LH = 120
        self.log_frame = tk.Frame(self.root, bg=C_PANEL,
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=(W - LW) // 2, y=H - LH - 32,
                             width=LW, height=LH)
        self.log_text = tk.Text(self.log_frame, fg=C_TEXT, bg=C_PANEL,
                                insertbackground=C_TEXT, borderwidth=0,
                                wrap="word", font=("Courier", 10),
                                padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#e8e8e8")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_ACC2)

        # ── First-launch API key setup ──
        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

    # ──────────────────────────────────────────────
    #  Image loading
    # ──────────────────────────────────────────────
    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        a = max(0, min(255, int(a)))
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _pri(self, alpha):
        """Primary HUD color with alpha, tinted by connection state."""
        return self._ac(*self._anim_rgb, alpha)

    # ──────────────────────────────────────────────
    #  Animation loop
    # ──────────────────────────────────────────────
    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        # ── Scale & halo targets ──
        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo  = random.uniform(138, 182)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo  = random.uniform(50, 68)
            self.last_t = now

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo  - self.halo_a) * sp

        # ── Ring rotations ──
        for i, spd in enumerate(
                [1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        self.scan_angle  = (self.scan_angle  + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        # ── Pulse rings ──
        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        # ── Orbiting particles ──
        for p in self._particles:
            spd_mult = 2.5 if self.speaking else 1.0
            p["angle"] = (p["angle"] + p["speed"] * spd_mult) % 360

        # ── Status blink ──
        if t % 40 == 0:
            self.status_blink = not self.status_blink

        # ── Animate color based on connection state ──
        _state_colors = {
            "ONLINE":       (0, 212, 255),
            "CONNECTING":   (255, 180, 0),
            "RECONNECTING": (255, 120, 0),
            "FAILED":       (255, 50, 50),
        }
        self._anim_rgb = _state_colors.get(
            getattr(self, 'conn_state', 'ONLINE'), (0, 212, 255))

        # ── Update visualizer bars ──
        for i in range(len(self._jarvis_bars)):
            tgt = (self.jarvis_level * random.uniform(0.3, 1.0)
                   if self.jarvis_level > 0.02 else random.uniform(0, 0.04))
            self._jarvis_bars[i] += (tgt - self._jarvis_bars[i]) * 0.35

        for i in range(len(self._mic_bars)):
            tgt = (self.mic_level * random.uniform(0.3, 1.0)
                   if self.mic_level > 0.02 else random.uniform(0, 0.04))
            self._mic_bars[i] += (tgt - self._mic_bars[i]) * 0.35

        # ── Shockwave management ──
        if self.jarvis_level > 0.15 and random.random() < 0.12:
            self._jarvis_shockwaves.append(0.0)
        if self.mic_level > 0.15 and random.random() < 0.12:
            self._mic_shockwaves.append(0.0)
        self._jarvis_shockwaves = [s + 2.5 for s in self._jarvis_shockwaves if s < 80]
        self._mic_shockwaves    = [s + 2.5 for s in self._mic_shockwaves if s < 80]

        # ── Gentle decay (in case main.py stops updating) ──
        self.mic_level    *= 0.88
        self.jarvis_level *= 0.88

        self._draw()
        self.root.after(16, self._animate)

    # ──────────────────────────────────────────────
    #  Main draw
    # ──────────────────────────────────────────────
    def _draw(self):
        c    = self.bg
        W, H = self.W, self.H
        t    = self.tick
        FCX  = self.FCX
        FCY  = self.FCY
        FW   = self.FACE_SZ
        c.delete("all")

        # ── Background grid with subtle variation ──
        for x in range(0, W, 44):
            for y in range(0, H, 44):
                a = 12 + int(6 * math.sin(x * 0.01 + y * 0.01 + t * 0.02))
                c.create_rectangle(x, y, x + 1, y + 1,
                                   fill=self._ac(0, 40, 55, a), outline="")

        # ── Horizontal scanline ──
        scan_y = int((t * 0.7) % H)
        c.create_line(0, scan_y, W, scan_y,
                      fill=self._pri(6), width=1)

        # ── Halo glow behind face ──
        for r in range(int(FW * 0.54), int(FW * 0.28), -22):
            frac = 1.0 - (r - FW * 0.28) / (FW * 0.26)
            ga   = max(0, min(255, int(self.halo_a * 0.09 * frac)))
            c.create_oval(FCX - r, FCY - r, FCX + r, FCY + r,
                          outline=self._pri(ga), width=2)

        # ── Pulse rings ──
        for pr in self.pulse_r:
            pa = max(0, int(220 * (1.0 - pr / (FW * 0.72))))
            r  = int(pr)
            c.create_oval(FCX - r, FCY - r, FCX + r, FCY + r,
                          outline=self._pri(pa), width=2)

        # ── Rotating arc rings ──
        for idx, (r_frac, w_ring, arc_l, gap) in enumerate([
                (0.47, 3, 110, 75), (0.39, 2, 75, 55), (0.31, 1, 55, 38)]):
            ring_r = int(FW * r_frac)
            base_a = self.rings_spin[idx]
            a_val  = max(0, min(255, int(self.halo_a * (1.0 - idx * 0.18))))
            col    = self._pri(a_val)
            for s in range(360 // (arc_l + gap)):
                start = (base_a + s * (arc_l + gap)) % 360
                c.create_arc(FCX - ring_r, FCY - ring_r,
                             FCX + ring_r, FCY + ring_r,
                             start=start, extent=arc_l,
                             outline=col, width=w_ring, style="arc")

        # ── Scanner arcs ──
        sr      = int(FW * 0.49)
        scan_a  = min(255, int(self.halo_a * 1.4))
        arc_ext = 70 if self.speaking else 42
        c.create_arc(FCX - sr, FCY - sr, FCX + sr, FCY + sr,
                     start=self.scan_angle, extent=arc_ext,
                     outline=self._pri(scan_a), width=3, style="arc")
        c.create_arc(FCX - sr, FCY - sr, FCX + sr, FCY + sr,
                     start=self.scan2_angle, extent=arc_ext,
                     outline=self._ac(255, 100, 0, scan_a // 2),
                     width=2, style="arc")

        # ── Tick marks ──
        t_out = int(FW * 0.495)
        t_in  = int(FW * 0.472)
        a_mk  = self._pri(155)
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 5
            c.create_line(
                FCX + t_out * math.cos(rad), FCY - t_out * math.sin(rad),
                FCX + inn  * math.cos(rad), FCY - inn  * math.sin(rad),
                fill=a_mk, width=1)

        # ── Crosshair ──
        ch_r = int(FW * 0.50)
        gap  = int(FW * 0.15)
        ch_a = self._pri(int(self.halo_a * 0.55))
        for x1, y1, x2, y2 in [
                (FCX - ch_r, FCY, FCX - gap, FCY),
                (FCX + gap, FCY, FCX + ch_r, FCY),
                (FCX, FCY - ch_r, FCX, FCY - gap),
                (FCX, FCY + gap, FCX, FCY + ch_r)]:
            c.create_line(x1, y1, x2, y2, fill=ch_a, width=1)

        # ── Bracket corners around face ──
        blen = 22
        bc   = self._pri(200)
        hl = FCX - FW // 2; hr = FCX + FW // 2
        ht = FCY - FW // 2; hb = FCY + FW // 2
        for bx, by, sdx, sdy in [(hl, ht, 1, 1), (hr, ht, -1, 1),
                                   (hl, hb, 1, -1), (hr, hb, -1, -1)]:
            c.create_line(bx, by, bx + sdx * blen, by, fill=bc, width=2)
            c.create_line(bx, by, bx, by + sdy * blen, fill=bc, width=2)

        # ── Orbiting particles ──
        for p in self._particles:
            rad = math.radians(p["angle"])
            px = FCX + p["r"] * math.cos(rad)
            py = FCY - p["r"] * math.sin(rad)
            pa = int(p["alpha"] * (1.5 if self.speaking else 0.7))
            ps = p["size"]
            c.create_oval(px - ps, py - ps, px + ps, py + ps,
                          fill=self._pri(min(255, pa)), outline="")

        # ── Face image ──
        if self._has_face:
            fw = int(FW * self.scale)
            if (self._face_scale_cache is None or
                    abs(self._face_scale_cache[0] - self.scale) > 0.004):
                scaled = self._face_pil.resize((fw, fw), Image.BILINEAR)
                tk_img = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, tk_img)
            c.create_image(FCX, FCY, image=self._face_scale_cache[1])
        else:
            orb_r = int(FW * 0.27 * self.scale)
            for i in range(7, 0, -1):
                r2   = int(orb_r * i / 7)
                frac = i / 7
                ga   = max(0, min(255, int(self.halo_a * 1.1 * frac)))
                c.create_oval(FCX - r2, FCY - r2, FCX + r2, FCY + r2,
                              fill=self._ac(0, int(65 * frac),
                                            int(120 * frac), ga),
                              outline="")
            c.create_text(FCX, FCY, text=SYSTEM_NAME,
                          fill=self._pri(min(255, int(self.halo_a * 2))),
                          font=("Courier", 14, "bold"))

        # ──────── HEADER ────────
        HDR = 62
        c.create_rectangle(0, 0, W, HDR, fill=C_HEADER, outline="")
        # Top accent line
        c.create_line(0, 0, W, 0, fill=C_PRI, width=1)
        c.create_line(0, HDR, W, HDR, fill=C_MID, width=1)

        c.create_text(W // 2, 22, text=SYSTEM_NAME,
                      fill=C_PRI, font=("Courier", 18, "bold"))
        c.create_text(W // 2, 44,
                      text="Just A Rather Very Intelligent System",
                      fill=C_MID, font=("Courier", 9))
        c.create_text(74, 31, text=MODEL_BADGE,
                      fill=C_DIM, font=("Courier", 9), anchor="w")
        c.create_text(W - 74, 31, text=time.strftime("%H:%M:%S"),
                      fill=C_PRI, font=("Courier", 14, "bold"), anchor="e")

        # ── Settings button (left header) ──
        sb_x, sb_y = 24, 31
        sb_col = C_PRI if self._hover_settings else C_DIM
        c.create_text(sb_x, sb_y, text="\u2699", fill=sb_col,
                      font=("Courier", 16), anchor="center")
        self._settings_btn_rect = (sb_x - 16, sb_y - 16,
                                   sb_x + 16, sb_y + 16)
        if self._hover_settings:
            x1, y1, x2, y2 = self._settings_btn_rect
            c.create_rectangle(x1, y1, x2, y2,
                               outline=C_PRI, fill="", width=1)

        # ── Close / Terminate button (right header) ──
        cb_x, cb_y = W - 24, 31
        cb_col = C_RED if self._hover_close else C_DIM
        c.create_text(cb_x, cb_y, text="\u2715", fill=cb_col,
                      font=("Courier", 16, "bold"), anchor="center")
        self._close_btn_rect = (cb_x - 16, cb_y - 16,
                                cb_x + 16, cb_y + 16)
        if self._hover_close:
            x1, y1, x2, y2 = self._close_btn_rect
            c.create_rectangle(x1, y1, x2, y2,
                               outline=C_RED, fill="", width=1)

        # ──────── STATUS TEXT ────────
        sy = FCY + FW // 2 + 30
        _cs = getattr(self, 'conn_state', 'ONLINE')
        if self.speaking:
            stat, sc = "\u25CF SPEAKING", C_ACC
        elif _cs == "CONNECTING":
            stat, sc = "\u25CE CONNECTING...", self._ac(255, 180, 0, 220)
        elif _cs == "RECONNECTING":
            stat, sc = "\u21BB RECONNECTING", self._ac(255, 120, 0, 220)
        elif _cs == "FAILED":
            stat, sc = "\u2715 CONNECTION FAILED", C_RED
        else:
            sym = "\u25CF" if self.status_blink else "\u25CB"
            stat, sc = f"{sym} {self.status_text}", self._pri(255)

        c.create_text(W // 2, sy, text=stat,
                      fill=sc, font=("Courier", 11, "bold"))

        # ──────── AUDIO VISUALIZERS ────────
        viz_y = sy + 50
        self._draw_jarvis_viz(c, int(W * 0.20), viz_y, 66)
        self._draw_mic_viz(c, int(W * 0.80), viz_y, 66)

        # ──────── CORNER HUD DATA ────────
        uptime = int(time.time() - self._start_time)
        up_str = time.strftime('%H:%M:%S', time.gmtime(uptime))
        hud_y_top = HDR + 10
        hud_y_bot = H - 56

        c.create_text(12, hud_y_top, text="SYS://MARK-XXX",
                      fill=self._ac(0, 80, 100, 100),
                      font=("Courier", 7), anchor="w")
        c.create_text(W - 12, hud_y_top, text=f"UPTIME {up_str}",
                      fill=self._ac(0, 80, 100, 100),
                      font=("Courier", 7), anchor="e")
        c.create_text(12, hud_y_bot,
                      text="\u25C8 NEURAL NET ACTIVE",
                      fill=self._ac(0, 80, 100, 80),
                      font=("Courier", 7), anchor="w")
        c.create_text(W - 12, hud_y_bot,
                      text="\u25C8 AUDIO STREAM LIVE",
                      fill=self._ac(0, 80, 100, 80),
                      font=("Courier", 7), anchor="e")

        # ──────── FOOTER ────────
        c.create_rectangle(0, H - 28, W, H, fill=C_HEADER, outline="")
        c.create_line(0, H - 28, W, H - 28, fill=C_DIM, width=1)
        c.create_text(W // 2, H - 14, fill=C_DIM, font=("Courier", 8),
                      text="Rahmonov.me  \u00b7  CLASSIFIED"
                           "")

    # ──────────────────────────────────────────────
    #  JARVIS Voice Visualizer — Arc-Reactor Plasma Core
    # ──────────────────────────────────────────────
    def _draw_jarvis_viz(self, c, cx, cy, r):
        level = max(self.jarvis_level, 0.08 if self.speaking else 0.0)
        t = self.tick
        is_active = level > 0.05

        # ── Glow halo (large, visible when active) ──
        if is_active:
            for i in range(3, 0, -1):
                gr = int(r + 12 * i + level * 8 * i)
                ga = int(level * 40 * (4 - i))
                c.create_oval(cx - gr, cy - gr, cx + gr, cy + gr,
                              outline=self._pri(min(255, ga)), width=2)

        # ── Shockwave rings ──
        for sw in self._jarvis_shockwaves:
            sw_r = int(r * 0.4 + sw)
            sw_a = max(0, int(180 * (1.0 - sw / 80)))
            c.create_oval(cx - sw_r, cy - sw_r, cx + sw_r, cy + sw_r,
                          outline=self._pri(sw_a), width=1)

        # ── Outer ring (thicker when active) ──
        ring_w = 3 if is_active else 1
        ring_a = int(60 + level * 195)
        c.create_oval(cx - r, cy - r, cx + r, cy + r,
                      outline=self._pri(ring_a), width=ring_w)

        # ── 2nd ring ──
        r2 = int(r * 0.88)
        c.create_oval(cx - r2, cy - r2, cx + r2, cy + r2,
                      outline=self._pri(int(30 + level * 100)), width=1)

        # ── Rotating arc segments (3 layers) ──
        for layer, (lr, n, spd_mult) in enumerate([
                (0.78, 8, 2.5), (0.62, 5, -1.8), (0.48, 3, 3.2)]):
            arc_r = int(r * lr)
            for i in range(n):
                angle = (t * (spd_mult if is_active else spd_mult * 0.3) + i * (360 / n)) % 360
                extent = 12 + level * 18
                a = int(40 + level * 200 - layer * 30)
                c.create_arc(cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r,
                             start=angle, extent=extent,
                             outline=self._pri(min(255, a)),
                             width=2, style="arc")

        # ── Radial energy bars (burst outward when active) ──
        nb = len(self._jarvis_bars)
        for i in range(nb):
            angle = math.radians(i * (360 / nb))
            bar_base = int(r * 0.52)
            bar_len  = int(r * 0.42 * self._jarvis_bars[i])
            x1 = cx + bar_base * math.cos(angle)
            y1 = cy - bar_base * math.sin(angle)
            x2 = cx + (bar_base + bar_len) * math.cos(angle)
            y2 = cy - (bar_base + bar_len) * math.sin(angle)
            # Color gradient: cyan → white at peak
            intensity = self._jarvis_bars[i]
            br = int(intensity * 255)
            bg = int(180 + intensity * 75)
            bb = 255
            ba = int(80 + intensity * 175)
            c.create_line(x1, y1, x2, y2,
                          fill=self._ac(br, bg, bb, min(255, ba)),
                          width=2 if intensity > 0.4 else 1)

        # ── Core glow (plasma effect) ──
        core_r = int(r * 0.32 * (1.0 + level * 0.5))
        for i in range(7, 0, -1):
            cr = int(core_r * i / 7)
            frac = i / 7
            ga = int((50 + level * 220) * frac)
            rr = int(level * 100 * frac)
            gg = int(160 + 80 * frac)
            bb = 255
            c.create_oval(cx - cr, cy - cr, cx + cr, cy + cr,
                          fill=self._ac(rr, gg, bb, min(255, ga)),
                          outline="")

        # ── Tiny center spark ──
        spark_r = int(3 + level * 4)
        c.create_oval(cx - spark_r, cy - spark_r, cx + spark_r, cy + spark_r,
                      fill=self._ac(200, 255, 255, int(120 + level * 135)),
                      outline="")

        # ── Labels ──
        label_col = self._pri(220 if is_active else 120)
        c.create_text(cx, cy + r + 18, text="J.A.R.V.I.S",
                      fill=label_col,
                      font=("Courier", 9, "bold"))
        status_txt = "▸ ACTIVE" if is_active else "▹ IDLE"
        status_col = self._ac(0, 255, 200, 220) if is_active else self._ac(0, 120, 160, 100)
        c.create_text(cx, cy + r + 32, text=status_txt,
                      fill=status_col,
                      font=("Courier", 7, "bold"))

    # ──────────────────────────────────────────────
    #  User Mic Visualizer — Waveform Pulse Ring
    # ──────────────────────────────────────────────
    def _draw_mic_viz(self, c, cx, cy, r):
        level = self.mic_level
        t = self.tick
        is_active = level > 0.05

        # ── Glow halo (large, visible when active) ──
        if is_active:
            for i in range(3, 0, -1):
                gr = int(r + 10 * i + level * 10 * i)
                ga = int(level * 45 * (4 - i))
                c.create_oval(cx - gr, cy - gr, cx + gr, cy + gr,
                              outline=self._ac(255, 160, 0, min(255, ga)), width=2)

        # ── Shockwave rings ──
        for sw in self._mic_shockwaves:
            sw_r = int(r * 0.3 + sw)
            sw_a = max(0, int(160 * (1.0 - sw / 80)))
            c.create_oval(cx - sw_r, cy - sw_r, cx + sw_r, cy + sw_r,
                          outline=self._ac(255, 180, 0, sw_a), width=1)

        # ── Outer ring ──
        ring_w = 3 if is_active else 1
        ring_a = int(50 + level * 205)
        c.create_oval(cx - r, cy - r, cx + r, cy + r,
                      outline=self._ac(255, 160, 0, ring_a), width=ring_w)

        # ── 2nd ring ──
        r2 = int(r * 0.88)
        c.create_oval(cx - r2, cy - r2, cx + r2, cy + r2,
                      outline=self._ac(255, 120, 0, int(25 + level * 80)), width=1)

        # ── Circular frequency bars (more bars, gradient coloring) ──
        nb      = len(self._mic_bars)
        inner_r = int(r * 0.30)
        for i in range(nb):
            angle   = math.radians(i * (360 / nb) - 90)
            bar_h   = self._mic_bars[i]
            bar_len = int((r - inner_r - 6) * (0.1 + 0.9 * bar_h))
            x1 = cx + inner_r * math.cos(angle)
            y1 = cy + inner_r * math.sin(angle)
            x2 = cx + (inner_r + bar_len) * math.cos(angle)
            y2 = cy + (inner_r + bar_len) * math.sin(angle)
            # Gradient: amber → bright yellow at peak
            rr = 255
            gg = int(120 + 135 * bar_h)
            bb = int(bar_h * 60)
            ba = int(70 + bar_h * 185)
            c.create_line(x1, y1, x2, y2,
                          fill=self._ac(rr, gg, bb, min(255, ba)),
                          width=2 if bar_h > 0.5 else 1)

        # ── Accent arcs (counter-rotating) ──
        accent_r = int(r * 0.92)
        spin = (t * (2.5 if is_active else 0.4)) % 360
        for i in range(3):
            arc_a = int(40 + level * 140)
            c.create_arc(cx - accent_r, cy - accent_r,
                         cx + accent_r, cy + accent_r,
                         start=(spin + i * 120) % 360,
                         extent=25 + level * 25,
                         outline=self._ac(255, 140, 0, min(255, arc_a)),
                         width=2, style="arc")

        # ── Inner counter-rotating arcs ──
        ir = int(r * 0.45)
        inner_spin = (t * (-1.5 if is_active else -0.4)) % 360
        for i in range(2):
            c.create_arc(cx - ir, cy - ir, cx + ir, cy + ir,
                         start=(inner_spin + i * 180) % 360,
                         extent=30 + level * 20,
                         outline=self._ac(255, 200, 50, int(30 + level * 120)),
                         width=1, style="arc")

        # ── Pulsing center dot (blooms on voice) ──
        dot_r = int(r * 0.22 * (1.0 + level * 0.6))
        for i in range(6, 0, -1):
            dr = int(dot_r * i / 6)
            da = int((40 + level * 200) * (i / 6))
            rr = 255
            gg = int(140 + 60 * (i / 6))
            bb = int(20 + 40 * (i / 6))
            c.create_oval(cx - dr, cy - dr, cx + dr, cy + dr,
                          fill=self._ac(rr, gg, bb, min(255, da)),
                          outline="")

        # ── Bright center spark ──
        spark_r = int(3 + level * 5)
        c.create_oval(cx - spark_r, cy - spark_r, cx + spark_r, cy + spark_r,
                      fill=self._ac(255, 255, 200, int(100 + level * 155)),
                      outline="")

        # ── Labels ──
        label_col = self._ac(255, 180, 0, 220 if is_active else 120)
        c.create_text(cx, cy + r + 18, text="USER MIC",
                      fill=label_col,
                      font=("Courier", 9, "bold"))
        status_txt = "▸ LISTENING" if is_active else "▹ STANDBY"
        status_col = self._ac(255, 220, 0, 220) if is_active else self._ac(255, 100, 0, 100)
        c.create_text(cx, cy + r + 32, text=status_txt,
                      fill=status_col,
                      font=("Courier", 7, "bold"))

    # ──────────────────────────────────────────────
    #  Log / typing
    # ──────────────────────────────────────────────
    def write_log(self, text: str):
        self.typing_queue.append(text)
        tl = text.lower()
        self.status_text = ("PROCESSING" if tl.startswith("you:")
                            else "RESPONDING" if tl.startswith("ai:")
                            else self.status_text)
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking:
                self.status_text = "ONLINE"
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        tag  = ("you" if tl.startswith("you:")
                else "ai" if tl.startswith("ai:")
                else "sys")
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(8, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(25, self._start_typing)

    # ──────────────────────────────────────────────
    #  Speaking state
    # ──────────────────────────────────────────────
    def start_speaking(self):
        self.speaking    = True
        self.status_text = "SPEAKING"

    def stop_speaking(self):
        self.speaking    = False
        self.status_text = "ONLINE"

    # ──────────────────────────────────────────────
    #  Canvas interaction
    # ──────────────────────────────────────────────
    def _on_canvas_click(self, event):
        if self._settings_open:
            return
        # ── Close / Terminate ──
        if self._close_btn_rect:
            x1, y1, x2, y2 = self._close_btn_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                os._exit(0)
        # ── Settings ──
        if self._settings_btn_rect:
            x1, y1, x2, y2 = self._settings_btn_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._show_settings()

    def _on_canvas_motion(self, event):
        self._hover_close    = False
        self._hover_settings = False
        if self._close_btn_rect:
            x1, y1, x2, y2 = self._close_btn_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._hover_close = True
        if self._settings_btn_rect:
            x1, y1, x2, y2 = self._settings_btn_rect
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._hover_settings = True
        if self._hover_close or self._hover_settings:
            self.bg.configure(cursor="hand2")
        else:
            self.bg.configure(cursor="")

    # ──────────────────────────────────────────────
    #  Settings modal
    # ──────────────────────────────────────────────
    def _show_settings(self):
        if self._settings_open:
            return
        self._settings_open = True

        modal_w, modal_h = 460, 380
        f = tk.Frame(self.root, bg="#010c10",
                     highlightbackground=C_PRI, highlightthickness=2)
        f.place(relx=0.5, rely=0.5, anchor="center",
                width=modal_w, height=modal_h)
        self._settings_frame = f

        # ── Header ──
        hdr = tk.Frame(f, bg="#010c10")
        hdr.pack(fill="x", padx=20, pady=(16, 0))
        tk.Label(hdr, text="\u25C8  SYSTEM SETTINGS",
                 fg=C_PRI, bg="#010c10",
                 font=("Courier", 13, "bold")).pack(side="left")
        tk.Button(hdr, text="\u2715", fg=C_DIM, bg="#010c10",
                  activeforeground=C_RED, activebackground="#010c10",
                  font=("Courier", 13, "bold"), borderwidth=0,
                  command=self._close_settings).pack(side="right")

        # ── Separator ──
        tk.Frame(f, bg=C_MID, height=1).pack(fill="x", padx=16,
                                              pady=(10, 0))

        # ── API key section ──
        tk.Label(f, text="\u25B8 API CONFIGURATION",
                 fg=C_PRI, bg="#010c10",
                 font=("Courier", 10, "bold")).pack(
                     anchor="w", padx=24, pady=(14, 0))
        tk.Label(f, text="GEMINI API KEY",
                 fg=C_DIM, bg="#010c10",
                 font=("Courier", 8)).pack(
                     anchor="w", padx=28, pady=(6, 2))

        key_frame = tk.Frame(f, bg="#010c10")
        key_frame.pack(fill="x", padx=28)

        current_key = ""
        if API_FILE.exists():
            try:
                with open(API_FILE, "r", encoding="utf-8") as fk:
                    current_key = json.load(fk).get("gemini_api_key", "")
            except Exception:
                pass

        self._settings_api_entry = tk.Entry(
            key_frame, width=36, fg=C_TEXT, bg="#000d12",
            insertbackground=C_TEXT, borderwidth=0,
            font=("Courier", 10), show="*")
        self._settings_api_entry.pack(side="left", fill="x",
                                      expand=True, ipady=4)
        self._settings_api_entry.insert(0, current_key)

        self._api_visible = False
        self._settings_vis_btn = tk.Button(
            key_frame, text="\u25CE", fg=C_DIM, bg="#001520",
            activebackground="#002530", font=("Courier", 10),
            borderwidth=0, padx=6,
            command=self._toggle_api_visibility)
        self._settings_vis_btn.pack(side="left", padx=(6, 0))

        btn_frame = tk.Frame(f, bg="#010c10")
        btn_frame.pack(fill="x", padx=28, pady=(8, 0))

        self._settings_save_btn = tk.Button(
            btn_frame, text="\U0001F4BE  SAVE KEY",
            fg=C_PRI, bg="#001520",
            activebackground="#003344", font=("Courier", 9),
            borderwidth=0, padx=12, pady=4,
            command=self._save_settings_api_key)
        self._settings_save_btn.pack(side="left")

        self._settings_status = tk.Label(
            btn_frame, text="", fg=C_GREEN, bg="#010c10",
            font=("Courier", 8))
        self._settings_status.pack(side="left", padx=(12, 0))

        # ── Separator ──
        tk.Frame(f, bg=C_DIM, height=1).pack(fill="x", padx=16,
                                              pady=(14, 0))

        # ── Auto-start section ──
        tk.Label(f, text="\u25B8 STARTUP PREFERENCES",
                 fg=C_PRI, bg="#010c10",
                 font=("Courier", 10, "bold")).pack(
                     anchor="w", padx=24, pady=(12, 0))

        auto_frame = tk.Frame(f, bg="#010c10")
        auto_frame.pack(fill="x", padx=28, pady=(8, 0))

        tk.Label(auto_frame, text="Auto-start with Windows",
                 fg=C_TEXT, bg="#010c10",
                 font=("Courier", 9)).pack(side="left")

        self._autostart_enabled = self._get_autostart_enabled()
        self._autostart_btn = tk.Button(
            auto_frame,
            text=("\u2B24 ENABLED" if self._autostart_enabled
                  else "\u25CB DISABLED"),
            fg=C_GREEN if self._autostart_enabled else C_RED,
            bg="#001520", activebackground="#002530",
            font=("Courier", 9, "bold"), borderwidth=0,
            padx=10, pady=2, command=self._toggle_autostart)
        self._autostart_btn.pack(side="right")

        # ── Info note ──
        tk.Label(f,
                 text="\u26A1 API key changes take effect after restart",
                 fg=self._ac(255, 200, 0, 100), bg="#010c10",
                 font=("Courier", 7)).pack(
                     anchor="w", padx=28, pady=(16, 0))

        # ── Close modal button ──
        tk.Button(f, text="CLOSE SETTINGS",
                  fg=C_MID, bg="#001520",
                  activebackground="#003344",
                  font=("Courier", 9), borderwidth=0,
                  padx=16, pady=6,
                  command=self._close_settings).pack(pady=(12, 0))

    def _close_settings(self):
        if self._settings_frame:
            self._settings_frame.destroy()
            self._settings_frame = None
        self._settings_open = False

    def _toggle_api_visibility(self):
        self._api_visible = not self._api_visible
        self._settings_api_entry.configure(
            show="" if self._api_visible else "*")
        self._settings_vis_btn.configure(
            text="\u25C9" if self._api_visible else "\u25CE",
            fg=C_PRI if self._api_visible else C_DIM)

    def _save_settings_api_key(self):
        new_key = self._settings_api_entry.get().strip()
        if not new_key:
            self._settings_status.configure(
                text="\u26A0 Key cannot be empty", fg=C_RED)
            return
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(API_FILE, "w", encoding="utf-8") as fh:
                json.dump({"gemini_api_key": new_key}, fh, indent=4)
            self._settings_status.configure(
                text="\u2713 Key saved successfully", fg=C_GREEN)
        except Exception as e:
            self._settings_status.configure(
                text=f"\u2715 Error: {e}", fg=C_RED)

    # ──────────────────────────────────────────────
    #  Auto-start (Windows registry)
    # ──────────────────────────────────────────────
    def _get_autostart_enabled(self):
        if sys.platform == "darwin":
            plist_path = os.path.expanduser("~/Library/LaunchAgents/com.jarvis.autorun.plist")
            return os.path.exists(plist_path)

        if not _HAS_WINREG:
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "JARVIS")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except Exception:
            return False

    def _set_autostart(self, enable):
        if sys.platform == "darwin":
            plist_path = os.path.expanduser("~/Library/LaunchAgents/com.jarvis.autorun.plist")
            try:
                if enable:
                    import stat
                    py_path = sys.executable
                    main_path = str(BASE_DIR / "main.py")
                    cwd_path = str(BASE_DIR)
                    plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.autorun</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py_path}</string>
        <string>{main_path}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{cwd_path}</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>'''
                    with open(plist_path, "w") as f:
                        f.write(plist_content)
                else:
                    if os.path.exists(plist_path):
                        os.remove(plist_path)
                return True
            except Exception as e:
                print(f"[UI] Auto-start mac error: {e}")
                return False

        if not _HAS_WINREG:
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE)
            if enable:
                python_path = os.path.abspath(sys.executable)
                script_path = str(BASE_DIR / "main.py")
                winreg.SetValueEx(
                    key, "JARVIS", 0, winreg.REG_SZ,
                    f'"{python_path}" "{script_path}"')
            else:
                try:
                    winreg.DeleteValue(key, "JARVIS")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"[UI] Auto-start registry error: {e}")
            return False

    def _toggle_autostart(self):
        new_state = not self._autostart_enabled
        success = self._set_autostart(new_state)
        if success:
            self._autostart_enabled = new_state
        self._autostart_btn.configure(
            text=("\u2B24 ENABLED" if self._autostart_enabled
                  else "\u25CB DISABLED"),
            fg=C_GREEN if self._autostart_enabled else C_RED)

    # ──────────────────────────────────────────────
    #  First-launch API key setup
    # ──────────────────────────────────────────────
    def _api_keys_exist(self):
        return API_FILE.exists()

    def wait_for_api_key(self):
        """Block until API key is saved (called from main thread
        before starting JARVIS)."""
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self):
        self.setup_frame = tk.Frame(
            self.root, bg="#00080d",
            highlightbackground=C_PRI, highlightthickness=1)
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(self.setup_frame,
                 text="\u25C8  INITIALISATION REQUIRED",
                 fg=C_PRI, bg="#00080d",
                 font=("Courier", 13, "bold")).pack(pady=(18, 4))
        tk.Label(self.setup_frame,
                 text="Enter your Gemini API key to boot J.A.R.V.I.S.",
                 fg=C_MID, bg="#00080d",
                 font=("Courier", 9)).pack(pady=(0, 10))

        tk.Label(self.setup_frame, text="GEMINI API KEY",
                 fg=C_DIM, bg="#00080d",
                 font=("Courier", 9)).pack(pady=(8, 2))
        self.gemini_entry = tk.Entry(
            self.setup_frame, width=52, fg=C_TEXT, bg="#000d12",
            insertbackground=C_TEXT, borderwidth=0,
            font=("Courier", 10), show="*")
        self.gemini_entry.pack(pady=(0, 4))

        tk.Button(
            self.setup_frame, text="\u25B8  INITIALISE SYSTEMS",
            command=self._save_api_keys, bg=C_BG, fg=C_PRI,
            activebackground="#003344", font=("Courier", 10),
            borderwidth=0, pady=8).pack(pady=14)

    def _save_api_keys(self):
        gemini = self.gemini_entry.get().strip()
        if not gemini:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(API_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_api_key": gemini}, f, indent=4)
        self.setup_frame.destroy()
        self._api_key_ready = True
        self.status_text = "ONLINE"
        self.write_log("SYS: Systems initialised. JARVIS online.")