"""Gameplay screen — note highway, lyrics (configurable), pitch, HUD.
Supports 1 or 2 simultaneous players with separate mics.
Video background supported when song has a video.mp4 file.
Vocal volume control: press [ / ] to lower/raise vocals, M to mute/unmute.
"""
import pygame, math, os
from screens.base_screen import BaseScreen
from engine.scorer import Scorer
from engine.audio_player import AudioPlayer
from engine.vocal_separator import VocalSeparator, DONE as SEP_DONE, RUNNING as SEP_RUNNING, ERROR as SEP_ERROR, UNAVAILABLE as SEP_UNAVAILABLE
from engine import config as CFG
from ui import theme as T, fonts as F
import ui.components as C
from ui.particles import ParticleSystem

COUNTDOWN     = 3
_P_COLORS     = [(255, 196, 28), (56, 160, 255)]
_MUSIC_END    = pygame.USEREVENT + 10   # fired by pygame when music track finishes


class GameplayScreen(BaseScreen):

    def __init__(self, game, song):
        super().__init__(game)
        self.song      = song
        self.audio     = AudioPlayer()
        self.particles = ParticleSystem()

        cfg            = CFG.get()
        self._cfg      = cfg
        self._two      = cfg.two_player
        n_players      = 2 if self._two else 1

        # Scorers — one per active player
        self.scorers   = [Scorer(song) for _ in range(n_players)]

        # Player colours from config
        self._p_colors = [
            tuple(cfg.player[i].get("color", _P_COLORS[i]))
            for i in range(n_players)
        ]
        self._p_names  = [
            cfg.player[i].get("name", f"Player {i+1}")
            for i in range(n_players)
        ]
        self._p_avatars= [
            cfg.player[i].get("avatar", "🎤")
            for i in range(n_players)
        ]

        # Per-player state
        self._hit_flash    = [0.0] * n_players
        self._last_combos  = [0]   * n_players
        self._feedback     = [""]  * n_players
        self._feedback_t   = [0.0] * n_players
        self._feedback_col = [T.GOLD] * n_players
        # Per-line rating popup (Vocaluxe-style)
        self._line_popup   = [""]  * n_players   # label
        self._line_popup_t = [0.0] * n_players   # time remaining
        self._line_popup_col = [T.GOLD] * n_players
        self._line_bonus_t = [0.0] * n_players   # "+N" bonus display

        # Global state
        self._elapsed  = -float(COUNTDOWN)
        self._state    = "countdown"
        self._paused   = False
        self._t        = 0.0

        # Display options (toggled via keyboard or on-screen buttons)
        self._highway_alpha  : int  = 255   # 0 = transparent, 255 = opaque
        self._lyrics_visible : bool = True
        self._notify_msg     : str  = ""
        self._notify_t       : float = 0.0
        # Clickable button rects (set each frame in draw)
        self._lyr_btn     : pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._pause_btn   : pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._stop_btn    : pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._slider_track: pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._slider_drag : bool        = False

        # Lyrics transition state
        self._ly_line_idx   = -1      # index of currently displayed line
        self._ly_trans_t    = 1.0     # 0→1: fade/slide in (1.0 = fully settled)
        self._ly_old_line   = None    # previous line (fading out)
        self._ly_old_trans  = 0.0    # how far old line has faded (0=visible,1=gone)

        # Pitch range for note highway
        self._pmin, self._pmax = song.pitch_range

        # Vocal separator — check for pre-separated stems first
        self._separator      = VocalSeparator()
        self._sep_notified   = False      # shown "vocal control ready" toast
        self._sep_toast_t    = 0.0        # seconds remaining for toast display
        self._vocal_muted    = False      # M key toggles mute
        self._vocal_vol_prev = 1.0        # volume before mute (restored on unmute)

        # Audio — load stems if available, otherwise original mp3
        if song.mp3_path:
            _stems_available = (song.folder and
                                VocalSeparator.stems_ready(song.folder))
            if _stems_available:
                self.audio.load_stems(
                    VocalSeparator.instrumental_path(song.folder),
                    VocalSeparator.vocals_path(song.folder),
                )
                self._separator._status = SEP_DONE    # mark done without re-running
            else:
                self.audio.load(song.mp3_path)
                # Kick off background separation so it's ready for next play
                if song.folder:
                    self._separator.start(song.mp3_path, song.folder)
            self.audio.set_volume(cfg.volume)
            self.audio.set_sync_offset(cfg.sync_offset_sec)
            pygame.mixer.music.set_endevent(_MUSIC_END)

        # Video background (optional — requires opencv)
        self._video_cap   = None    # cv2.VideoCapture
        self._video_surf  = None    # current frame as pygame Surface
        self._video_fps   = 30.0
        self._video_frame_t = 0.0   # time of last video frame seek
        self._video_alpha = 80      # overlay alpha (0=invisible, 255=opaque)
        video_file = (os.path.join(song.folder, song.video)
                      if song.video and song.folder else None)
        if video_file and os.path.exists(video_file):
            try:
                import cv2
                cap = cv2.VideoCapture(video_file)
                if cap.isOpened():
                    self._video_cap = cap
                    self._video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            except Exception as e:
                print(f"[Video] {e}")

        # Lyrics config
        ly = cfg.lyrics
        self._ly_slot  = ly.get("font_slot",    "body_bold")
        self._ly_size  = ly.get("size",           36)
        self._ly_col   = tuple(ly.get("color",   [255,255,255]))
        self._ly_acol  = tuple(ly.get("active_color", [255,196,28]))
        self._ly_scol  = tuple(ly.get("sung_color",   [105,105,120]))

        # Mic is started once at app launch (Game.__init__) and stays open

    # ── Input ─────────────────────────────────────────────────────────────

    def _alpha_from_x(self, mx: int):
        """Map a mouse x coordinate to a highway alpha value via the slider track."""
        t = max(0.0, min(1.0, (mx - self._slider_track.x) / max(1, self._slider_track.width)))
        self._highway_alpha = int(t * 255)

    def handle_event(self, event):
        if event.type == _MUSIC_END and self._state == "playing":
            self._finish()
            return

        # Slider drag (MOUSEMOTION / MOUSEBUTTONUP)
        if event.type == pygame.MOUSEMOTION:
            if self._slider_drag and event.buttons[0]:
                self._alpha_from_x(event.pos[0])
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._slider_drag = False

        # Display-option buttons and control buttons (mouse)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._slider_track.collidepoint(event.pos):
                self._slider_drag = True
                self._alpha_from_x(event.pos[0])
                return
            if self._pause_btn.collidepoint(event.pos):
                self._toggle_pause()
                return
            if self._stop_btn.collidepoint(event.pos):
                self._finish()
                return
            if self._lyr_btn.collidepoint(event.pos):
                self._toggle_lyrics_visible()
                return
        # Home button
        if self.handle_home_click(event):
            # _finish() already called inside go_home via cleanup
            self.audio.stop()
            pygame.mixer.music.set_endevent(0)
            if self._video_cap:
                try:
                    self._video_cap.release()
                except Exception:
                    pass
                self._video_cap = None
            return
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            self._finish()
        elif event.key == pygame.K_p:
            self._toggle_pause()
        elif event.key == pygame.K_LEFTBRACKET:
            self._adjust_vocal_volume(-0.1)
        elif event.key == pygame.K_RIGHTBRACKET:
            self._adjust_vocal_volume(+0.1)
        elif event.key == pygame.K_m:
            self._toggle_vocal_mute()
        elif event.key == pygame.K_h:
            self._cycle_highway_alpha()
        elif event.key == pygame.K_l:
            self._toggle_lyrics_visible()

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.audio.pause()
        else:
            self.audio.unpause()

    def _adjust_vocal_volume(self, delta: float):
        """Nudge vocal volume by delta (works only with stems loaded)."""
        if not self.audio.stems_loaded:
            return
        self._vocal_muted = False
        new_v = max(0.0, min(1.0, self.audio.vocal_volume + delta))
        self.audio.set_vocal_volume(new_v)

    def _toggle_vocal_mute(self):
        """M key: mute/unmute vocal stem."""
        if not self.audio.stems_loaded:
            return
        if self._vocal_muted:
            # Unmute — restore previous volume
            self.audio.set_vocal_volume(self._vocal_vol_prev)
            self._vocal_muted = False
        else:
            self._vocal_vol_prev = self.audio.vocal_volume
            self.audio.set_vocal_volume(0.0)
            self._vocal_muted = True

    # Highway opacity steps: 100% → 78% → 51% → 24% → 0%
    _HW_ALPHA_STEPS = (255, 200, 130, 60, 0)

    def _cycle_highway_alpha(self):
        steps = self._HW_ALPHA_STEPS
        cur   = min(range(len(steps)), key=lambda i: abs(steps[i] - self._highway_alpha))
        self._highway_alpha = steps[(cur + 1) % len(steps)]
        pct = int(self._highway_alpha / 255 * 100)
        label = "opaque" if pct == 100 else ("transparent" if pct == 0 else f"{pct}%")
        self._notify(f"Highway: {label}")

    def _toggle_lyrics_visible(self):
        self._lyrics_visible = not self._lyrics_visible
        self._notify("Lyrics: " + ("ON" if self._lyrics_visible else "OFF"))

    def _notify(self, msg: str, duration: float = 2.2):
        self._notify_msg = msg
        self._notify_t   = duration

    def _finish(self):
        self.audio.stop()
        pygame.mixer.music.set_endevent(0)   # clear so it doesn't fire on next screen
        if self._video_cap is not None:
            try:
                self._video_cap.release()
            except Exception:
                pass
            self._video_cap = None
        self.game.show_results(self.scorers[0].state, self.song)

    # ── Update ────────────────────────────────────────────────────────────

    def update(self, dt):
        if self._paused:
            return
        self._elapsed += dt
        self._t       += dt

        if self._state == "countdown" and self._elapsed >= 0:
            self._state = "playing"
            if self.song.mp3_path:
                self.audio.play()

        if self._state == "playing":
            self.audio.update()
            cur = self._cur_sec()

            mics = self.game.mic_manager.players
            for pi, scorer in enumerate(self.scorers):
                midi = mics[pi].midi_note if pi < len(mics) else -1.0
                hit  = scorer.update(midi, cur, dt)

                if hit:
                    self._hit_flash[pi] = min(1.0, self._hit_flash[pi] + dt*7)
                    ny = self._pitch_y(midi)
                    col = self._p_colors[pi]
                    self.particles.stream(T.CURRENT_X, ny, col, count=2, size=3, speed=40)
                else:
                    self._hit_flash[pi] = max(0.0, self._hit_flash[pi] - dt*5)

                combo = scorer.state.combo
                if combo > self._last_combos[pi]:
                    if combo % 10 == 0:
                        self.particles.burst(
                            T.CURRENT_X, (T.HIGHWAY_TOP+T.HIGHWAY_BOT)//2,
                            self._p_colors[pi], count=20, size=6)
                        self._feedback[pi]     = f"{combo} COMBO"
                        self._feedback_t[pi]   = 1.4
                        self._feedback_col[pi] = self._p_colors[pi]
                    self._last_combos[pi] = combo
                self._feedback_t[pi]    = max(0.0, self._feedback_t[pi] - dt)
                self._line_popup_t[pi]  = max(0.0, self._line_popup_t[pi] - dt)
                self._line_bonus_t[pi]  = max(0.0, self._line_bonus_t[pi] - dt)

                # Vocaluxe-style per-line rating popup
                lr = scorer.line_result
                if lr is not None:
                    self._line_popup[pi]     = lr.label
                    self._line_popup_t[pi]   = 1.8
                    self._line_popup_col[pi] = lr.color
                    self._feedback[pi]       = f"+{lr.bonus:,}"
                    self._feedback_t[pi]     = 1.2
                    self._feedback_col[pi]   = lr.color
                    if lr.pct >= 1.0:
                        self.particles.burst(
                            T.SCREEN_W//2,
                            T.LYRICS_Y - 20,
                            T.GOLD, count=35, size=7)

            # Note-based end: only for songs that have notes
            if self.song.notes and cur >= self.song.duration_sec:
                self._finish()

            # Track lyric line transitions
            _, new_idx = self.song.line_at_sec(cur)
            if new_idx != self._ly_line_idx and new_idx != -1:
                all_lines = list(self.song.lines())
                if 0 <= self._ly_line_idx < len(all_lines):
                    self._ly_old_line  = all_lines[self._ly_line_idx]
                else:
                    self._ly_old_line  = None
                self._ly_line_idx  = new_idx
                self._ly_trans_t   = 0.0   # start slide-in
                self._ly_old_trans = 0.0   # start fade-out of old line

        # Tick notification timer
        if self._notify_t > 0:
            self._notify_t = max(0.0, self._notify_t - dt)

        # Poll vocal separator — show toast when stems become available
        if not self._sep_notified:
            sep_st = self._separator.status
            if sep_st == SEP_DONE:
                self._sep_notified = True
                if not self.audio.stems_loaded:
                    # Stems finished while we were playing original — notify user
                    self._sep_toast_t = 5.0
            elif sep_st == SEP_ERROR:
                self._sep_notified = True   # don't keep polling
        if self._sep_toast_t > 0:
            self._sep_toast_t = max(0.0, self._sep_toast_t - dt)

        # Advance transition timers (outside playing check so they finish cleanly)
        if self._ly_trans_t < 1.0:
            self._ly_trans_t = min(1.0, self._ly_trans_t + dt * 4.0)
        if self._ly_old_line is not None:
            self._ly_old_trans = min(1.0, self._ly_old_trans + dt * 5.0)
            if self._ly_old_trans >= 1.0:
                self._ly_old_line = None

        self.particles.update(dt)
        self._update_video()

    def _update_video(self):
        """Decode next video frame when appropriate."""
        if self._video_cap is None or self._state != "playing":
            return
        import cv2
        cur = self._cur_sec()
        # Seek video to match audio position (once per frame window)
        target_frame = int(cur * self._video_fps)
        current_frame = int(self._video_cap.get(cv2.CAP_PROP_POS_FRAMES))
        # Only re-seek if we're more than 1 frame out of sync
        if abs(target_frame - current_frame) > 1:
            self._video_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = self._video_cap.read()
        if not ret:
            return
        # Convert BGR → RGB then to pygame Surface
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]
        # Scale to screen while preserving aspect ratio
        scale = min(T.SCREEN_W / w, T.SCREEN_H / h)
        nw, nh = int(w * scale), int(h * scale)
        frame_rgb = cv2.resize(frame_rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        surf = pygame.surfarray.make_surface(frame_rgb.swapaxes(0, 1))
        # Center on screen
        full = pygame.Surface((T.SCREEN_W, T.SCREEN_H))
        full.fill(T.BG)
        full.blit(surf, ((T.SCREEN_W - nw) // 2, (T.SCREEN_H - nh) // 2))
        full.set_alpha(self._video_alpha)
        self._video_surf = full

    def _cur_sec(self):
        return self.audio.position_sec() if self.song.mp3_path else self._elapsed

    # ── Draw ──────────────────────────────────────────────────────────────

    def draw(self, surf):
        surf.fill(T.BG)
        # Video background (behind everything)
        if self._video_surf is not None:
            surf.blit(self._video_surf, (0, 0),
                      special_flags=pygame.BLEND_RGBA_ADD)
        self._draw_highway(surf)
        # Home button (top-right, over HUD)
        self.draw_home_btn(surf, y=T.HUD_H + 8, w=90, h=26)
        self._draw_notes(surf)
        for pi in range(len(self.scorers)):
            self._draw_player_dot(surf, pi)
        self._draw_hud(surf)
        if self._lyrics_visible:
            self._draw_lyrics(surf)
        self._draw_hint(surf)
        self.particles.draw(surf)
        if self._state == "countdown":
            self._draw_countdown(surf)
        if self._paused:
            self._draw_pause(surf)
        if self._sep_toast_t > 0:
            self._draw_sep_toast(surf)
        self._draw_display_btns(surf)
        if self._notify_t > 0:
            self._draw_notify(surf)

    # ── Highway ───────────────────────────────────────────────────────────

    def _pitch_y(self, pitch):
        span = max(1, self._pmax - self._pmin)
        t    = 1.0 - (pitch - self._pmin) / span
        return int(T.HIGHWAY_TOP + t * (T.HIGHWAY_BOT - T.HIGHWAY_TOP))

    def _beat_x(self, sec, cur):
        total = T.LOOK_BACK + T.LOOK_AHEAD
        rel   = (sec - cur + T.LOOK_BACK) / total
        return int(T.HIGHWAY_LEFT + rel * (T.HIGHWAY_RIGHT - T.HIGHWAY_LEFT))

    def _draw_highway(self, surf):
        hw_w = T.HIGHWAY_RIGHT - T.HIGHWAY_LEFT
        hw_h = T.HIGHWAY_BOT   - T.HIGHWAY_TOP
        a    = self._highway_alpha   # 0 = transparent, 255 = opaque

        # ── Background + grid on an SRCALPHA surface (configurable opacity) ──
        if a > 0:
            hw_s = pygame.Surface((hw_w, hw_h), pygame.SRCALPHA)
            hw_s.fill((*T.HIGHWAY_BG, a))
            for pitch in range(int(self._pmin), int(self._pmax) + 1):
                if   pitch % 12 == 0: col, lw = T.HIGHWAY_GRID,  2
                elif pitch %  6 == 0: col, lw = T.HIGHWAY_GRID2, 1
                else: continue
                gy = self._pitch_y(pitch) - T.HIGHWAY_TOP
                pygame.draw.line(hw_s, (*col, a), (0, gy), (hw_w, gy), lw)
            # Border stays slightly more visible than the fill
            pygame.draw.rect(hw_s, (*T.HIGHWAY_GRID, min(255, a + 80)),
                             hw_s.get_rect(), 1)
            surf.blit(hw_s, (T.HIGHWAY_LEFT, T.HIGHWAY_TOP))

        # ── Current-time marker glow — always shown at full opacity ──────────
        pygame.draw.line(surf, T.GOLD_DIM,
                         (T.CURRENT_X, T.HIGHWAY_TOP),
                         (T.CURRENT_X, T.HIGHWAY_BOT), 2)
        gw = 12
        gs = pygame.Surface((gw, hw_h), pygame.SRCALPHA)
        for i in range(gw // 2):
            ga = max(0, int(50 - i * 8))
            pygame.draw.line(gs, (*T.GOLD, ga), (gw//2-i, 0), (gw//2-i, hw_h))
            pygame.draw.line(gs, (*T.GOLD, ga), (gw//2+i, 0), (gw//2+i, hw_h))
        surf.blit(gs, (T.CURRENT_X - gw//2, T.HIGHWAY_TOP),
                  special_flags=pygame.BLEND_RGBA_ADD)

    def _draw_notes(self, surf):
        from engine.song_parser import Note as N
        cur   = self._cur_sec()
        ws,we = cur-T.LOOK_BACK, cur+T.LOOK_AHEAD
        midi0 = self.game.mic_manager.players[0].midi_note
        hh    = T.HIGHWAY_BOT - T.HIGHWAY_TOP
        span  = max(1, self._pmax - self._pmin)
        nh    = max(10, min(28, hh//span - 2))

        for n in self.song.notes:
            if not isinstance(n,N) or n.note_type=="F":
                continue
            ns = self.song.beat_to_sec(n.beat)
            ne = self.song.beat_to_sec(n.beat+n.duration)
            if ne<ws or ns>we: continue
            x1 = self._beat_x(ns, cur)
            x2 = self._beat_x(ne, cur)
            w  = max(8, x2-x1)
            py = self._pitch_y(float(n.pitch))
            r  = pygame.Rect(x1, py-nh//2, w, nh)
            active = ns<=cur<=ne
            golden = n.note_type=="*"
            on = False
            if active and midi0>0:
                diff=(midi0-n.pitch)%12
                if diff>6: diff-=12
                on=abs(diff)<=2.5
            if on:
                col  = T.NOTE_GOLDEN_HIT if golden else T.NOTE_HIT
                glow = T.GOLD if golden else T.SUCCESS
            elif golden:
                shim = C.pulse(self._t,3.0)
                col  = T.NOTE_GOLDEN; glow=T.GOLD_DIM if active else None
                s2   = pygame.Surface((w,nh),pygame.SRCALPHA)
                s2.fill((*T.GOLD,int(40*shim)))
                surf.blit(s2,r.topleft,special_flags=pygame.BLEND_RGBA_ADD)
            else:
                col  = T.NOTE_NORMAL if not active else (210,210,235)
                glow = None
            C.note_bar(surf, r, col, glow)

    def _draw_player_dot(self, surf, pi: int):
        mics = self.game.mic_manager.players
        midi = mics[pi].midi_note if pi < len(mics) else -1.0
        if midi < 0:
            return
        py  = max(T.HIGHWAY_TOP+12, min(T.HIGHWAY_BOT-12, self._pitch_y(midi)))
        hf  = self._hit_flash[pi]
        col = tuple(self._p_colors[pi])

        # Offset x slightly for p2 so dots don't overlap
        cx  = T.CURRENT_X + pi * 16
        r   = 10 + int(4*hf)

        gs = pygame.Surface((r*5, r*5), pygame.SRCALPHA)
        pygame.draw.circle(gs, (*col, int(60*hf)), (r*5//2,r*5//2), r*5//2)
        surf.blit(gs,(cx-r*5//2, py-r*5//2), special_flags=pygame.BLEND_RGBA_ADD)

        pygame.draw.circle(surf, col, (cx,py), r)
        pygame.draw.circle(surf, T.TEXT_1, (cx,py), max(2,r//3))

    # ── HUD ───────────────────────────────────────────────────────────────

    def _draw_hud(self, surf):
        hb = pygame.Surface((T.SCREEN_W, T.HUD_H), pygame.SRCALPHA)
        hb.fill((*T.BG_PANEL, 235))
        surf.blit(hb,(0,0))
        C.h_divider(surf,0,T.SCREEN_W,T.HUD_H,color=T.HIGHWAY_GRID,alpha=200)

        if self._two:
            # Split HUD: P1 left, P2 right, stars center
            for pi, scorer in enumerate(self.scorers):
                st  = scorer.state
                col = tuple(self._p_colors[pi])
                nm  = self._p_names[pi]
                av  = self._p_avatars[pi]
                if pi == 0:
                    x_score = 20; x_score_anchor = "topleft"
                    x_mult  = 240
                else:
                    x_score = T.SCREEN_W-20; x_score_anchor = "topright"
                    x_mult  = T.SCREEN_W-240
                C.text(surf, f"{av} {nm}", "cond_bold", 12, col,
                       20 if pi==0 else T.SCREEN_W-20, 8,
                       anchor="topleft" if pi==0 else "topright", uppercase=True)
                C.text_shadow(surf, f"{st.total_score:,}", "num_black", 34, col,
                              x_score, 22,
                              anchor=x_score_anchor,
                              shadow_color=(0,0,0), offset=(2,2))
                C.multiplier_badge(surf, x_mult, T.HUD_H//2, st.multiplier)
            # Stars center
            st0 = self.scorers[0].state
            C.stars_row(surf, T.SCREEN_W//2, T.HUD_H//2+6, 5, st0.stars,
                        spacing=36, r=12)
        else:
            st = self.scorers[0].state
            # Score — left
            C.text(surf, "SCORE", "cond_bold", 11, T.TEXT_3, 20, 8, uppercase=True)
            C.text_shadow(surf, f"{st.total_score:,}", "num_black", 38, T.GOLD,
                          20, 20, shadow_color=(60, 40, 0), offset=(2, 2))
            # Multiplier badge at CURRENT_X so it sits above the yellow time-marker
            C.multiplier_badge(surf, T.CURRENT_X, T.HUD_H // 2, st.multiplier)
            # Stars — center
            C.stars_row(surf, T.SCREEN_W // 2, T.HUD_H // 2 + 6, 5, st.stars,
                        spacing=42, r=14)
            # Accuracy — right column (compact, no overlap)
            acc   = int(st.accuracy * 100)
            col_a = (T.SUCCESS if acc >= 80 else T.WARNING if acc >= 50 else T.RED)
            rpad  = T.SCREEN_W - 14
            C.text(surf, "ACCURACY", "cond_bold", 11, T.TEXT_3,
                   rpad, 8, anchor="topright", uppercase=True)
            C.text(surf, f"{acc}%", "num_bold", 26, col_a,
                   rpad, 20, anchor="topright")
            # Mic level bar — below accuracy
            vol = min(1.0, self.game.mic_manager.volume * 20)
            bar_r = pygame.Rect(T.SCREEN_W - 124, 50, 110, 8)
            C.progress_bar(surf, bar_r, vol, color=T.INFO, bg=T.HIGHWAY_GRID)
            # Vocal volume control — bottom of HUD, right side
            self._draw_vocal_control(surf, T.SCREEN_W - 124, 62)

        # Feedback labels (combo count / line bonus "+N")
        for pi in range(len(self.scorers)):
            fx = T.SCREEN_W//2 + (pi-0.5)*300 if self._two else T.SCREEN_W//2
            if self._feedback_t[pi] > 0:
                a   = min(255, int(min(1.0, self._feedback_t[pi]) * 255))
                col = tuple(self._feedback_col[pi])
                C.text(surf, self._feedback[pi], "body_xbold", 24, col,
                       int(fx), T.HUD_H + 12, anchor="midtop",
                       uppercase=True, alpha=a)

            # Vocaluxe-style per-line rating popup above lyrics
            if self._line_popup_t[pi] > 0:
                frac  = self._line_popup_t[pi] / 1.8
                a     = min(255, int(frac * 255))
                rise  = int((1.0 - frac) * 28)    # floats upward as it fades
                col_p = tuple(self._line_popup_col[pi])
                py    = T.LYRICS_Y - 52 - rise + (pi * 38 if self._two else 0)
                # Shadow
                C.text(surf, self._line_popup[pi], "body_xbold", 28,
                       (0, 0, 0),
                       int(fx)+2, py+2, anchor="center", uppercase=True,
                       alpha=a//2)
                C.text(surf, self._line_popup[pi], "body_xbold", 28,
                       col_p,
                       int(fx), py, anchor="center", uppercase=True,
                       alpha=a)

    # ── Lyrics ────────────────────────────────────────────────────────────

    def _render_line(self, surf, line, cur, y, alpha=255, scale=1.0):
        """Render a lyric line with per-syllable colouring at position y."""
        if not line:
            return
        slot = self._ly_slot
        sz   = int(self._ly_size * scale)
        parts = [(n.text,
                  self.song.beat_to_sec(n.beat),
                  self.song.beat_to_sec(n.beat + n.duration))
                 for n in line]
        total_w = sum(F.get(slot, sz).size(t)[0] for t, *_ in parts)
        cx = T.SCREEN_W // 2 - total_w // 2
        for txt, ts, te in parts:
            col = (self._ly_acol if cur >= ts and cur <= te
                   else self._ly_scol if cur > te
                   else self._ly_col)
            img = F.get(slot, sz).render(txt, True, col)
            if alpha < 255:
                img.set_alpha(alpha)
            surf.blit(img, (cx, y))
            cx += img.get_width()

    def _draw_lyrics(self, surf):
        cur = self._cur_sec()

        # Audio-only stub — no karaoke data available
        if not self.song.notes:
            C.text(surf, "No lyrics available for this song",
                   "body_reg", 20, T.TEXT_3,
                   T.SCREEN_W // 2, T.LYRICS_Y + 10, anchor="midtop")
            C.text(surf, "Sing freely — ESC to finish",
                   "body_reg", 15, T.TEXT_3,
                   T.SCREEN_W // 2, T.LYRICS_Y + 42, anchor="midtop")
            return

        all_lines = list(self.song.lines())
        if not all_lines:
            return

        # Easing function: smooth cubic
        def ease(t): return t * t * (3 - 2 * t)

        line_h  = self._ly_size + 8
        preview_sz = max(16, self._ly_size - 10)
        preview2_sz = max(13, self._ly_size - 16)

        # ── Outgoing line (slide up & fade out) ───────────────────────────
        if self._ly_old_line is not None:
            t = ease(min(1.0, self._ly_old_trans))
            a = int(255 * (1.0 - t))
            slide = int(t * line_h * 0.6)
            self._render_line(surf, self._ly_old_line, cur,
                              T.LYRICS_Y - slide, alpha=a)

        # ── Current line (slide in from below, fade in) ───────────────────
        if 0 <= self._ly_line_idx < len(all_lines):
            line = all_lines[self._ly_line_idx]
            t    = ease(self._ly_trans_t)
            a    = int(255 * t)
            drop = int((1.0 - t) * line_h * 0.7)   # slides up from below
            self._render_line(surf, line, cur,
                              T.LYRICS_Y + drop, alpha=a)

            # ── Next line preview (coming up) ─────────────────────────────
            next_idx = self._ly_line_idx + 1
            if next_idx < len(all_lines):
                next_line = all_lines[next_idx]
                ntxt      = "".join(n.text for n in next_line)
                # Dim preview — brightens slightly as current line nears its end
                if line:
                    line_end = self.song.beat_to_sec(
                        line[-1].beat + line[-1].duration)
                    time_left = line_end - cur
                    # Start brightening when <2s left in the line
                    preview_a = int(80 + min(100, max(0, (2.0 - time_left) / 2.0 * 100)))
                else:
                    preview_a = 80
                preview_a = max(60, min(180, int(preview_a * t)))
                C.text(surf, ntxt, "body_reg", preview_sz, T.TEXT_3,
                       T.SCREEN_W // 2, T.LYRICS_Y + line_h + 4,
                       anchor="midtop", alpha=preview_a)

            # ── Two-lines-ahead preview (very faint) ─────────────────────
            if next_idx + 1 < len(all_lines):
                line2 = all_lines[next_idx + 1]
                l2txt = "".join(n.text for n in line2)
                C.text(surf, l2txt, "body_reg", preview2_sz, T.TEXT_3,
                       T.SCREEN_W // 2, T.LYRICS_Y + line_h + preview_sz + 10,
                       anchor="midtop", alpha=35)

        # ── No active line — show nearest upcoming line as preview ────────
        elif self._ly_line_idx == -1:
            # Find the next upcoming line
            for i, ln in enumerate(all_lines):
                if ln and self.song.beat_to_sec(ln[0].beat) > cur:
                    ntxt = "".join(n.text for n in ln)
                    # Pulse gently so singer knows what's coming
                    pulse_a = int(100 + 60 * C.pulse(self._t, 1.2))
                    C.text(surf, ntxt, "body_reg", preview_sz, T.TEXT_3,
                           T.SCREEN_W // 2, T.LYRICS_Y + 4,
                           anchor="midtop", alpha=pulse_a)
                    break

    def _draw_vocal_control(self, surf, x: int, y: int):
        """Draw a compact vocal volume bar + status at position (x, y)."""
        sep_st = self._separator.status
        bar_w  = 110

        if self.audio.stems_loaded:
            # Stems active — show interactive slider
            vv   = self.audio.vocal_volume
            mute = self._vocal_muted
            label_col = T.TEXT_3 if not mute else T.RED
            val_col   = T.GOLD   if not mute else T.RED
            label = "VOCAL (M=MUTE)" if not mute else "VOCAL (MUTED)"
            C.text(surf, label, "cond_bold", 11, label_col,
                   x, y, uppercase=True)
            bar_col = T.GOLD if not mute else T.RED
            bar_r = pygame.Rect(x, y + 12, bar_w, 8)
            C.progress_bar(surf, bar_r, vv, color=bar_col, bg=T.HIGHWAY_GRID)
            # Current percentage
            pct_x = x + bar_w + 4
            C.text(surf, f"{int(vv*100)}%", "cond_bold", 11, val_col,
                   pct_x, y + 10, anchor="topleft")
        elif sep_st == SEP_RUNNING:
            # Separation in progress — show spinner/label
            dot_cnt = int(self._t * 2) % 4
            dots    = "." * dot_cnt
            C.text(surf, f"PREPARING VOCAL{dots}", "cond_bold", 11, T.TEXT_3,
                   x, y, uppercase=True)
            # Indeterminate progress bar (animated sweep)
            sweep = (math.sin(self._t * 2.5) + 1) / 2
            bar_r = pygame.Rect(x, y + 12, bar_w, 8)
            C.progress_bar(surf, bar_r, sweep, color=T.HIGHWAY_GRID2, bg=T.HIGHWAY_GRID)
        elif sep_st == SEP_DONE and not self.audio.stems_loaded:
            # Stems ready but loaded with original audio — prompt restart
            a = int(180 + 60 * math.sin(self._t * 3))
            C.text(surf, "VOCAL READY - REPLAY SONG", "cond_bold", 11,
                   T.SUCCESS, x, y, uppercase=True, alpha=a)
        elif sep_st == SEP_ERROR:
            C.text(surf, "VOCAL PREP FAILED", "cond_bold", 11, T.RED,
                   x, y, uppercase=True)
        elif sep_st == SEP_UNAVAILABLE:
            C.text(surf, "DEMUCS NOT INSTALLED", "cond_bold", 11, T.TEXT_3,
                   x, y, uppercase=True)
        # else IDLE — nothing to show

    def _draw_display_btns(self, surf):
        """Single-row control strip anchored safely inside the bottom of the screen."""
        BTN_H = 32
        # Strip sits at HIGHWAY_BOT + 14 so it's always inside the game area
        by = T.HIGHWAY_BOT + 14

        # Semi-transparent strip background
        strip = pygame.Surface((T.SCREEN_W, BTN_H + 8), pygame.SRCALPHA)
        strip.fill((10, 10, 18, 180))
        surf.blit(strip, (0, by - 4))

        # ── ⏸ PAUSE / ▶ RESUME ───────────────────────────────────────────────
        pause_w = 96
        pause_r = pygame.Rect(10, by, pause_w, BTN_H)
        self._pause_btn = pause_r
        paused    = self._paused
        p_col     = T.GOLD if paused else T.INFO
        pygame.draw.rect(surf, T.BG_CARD, pause_r, border_radius=7)
        pygame.draw.rect(surf, p_col, pause_r, 1, border_radius=7)
        C.text(surf, "▶ RESUME" if paused else "⏸ PAUSE", "cond_bold", 12, p_col,
               pause_r.centerx, pause_r.centery, anchor="center", uppercase=True)

        # ── ⏹ STOP ────────────────────────────────────────────────────────────
        stop_r = pygame.Rect(pause_r.right + 6, by, 80, BTN_H)
        self._stop_btn = stop_r
        pygame.draw.rect(surf, T.BG_CARD, stop_r, border_radius=7)
        pygame.draw.rect(surf, T.RED, stop_r, 1, border_radius=7)
        C.text(surf, "⏹ STOP", "cond_bold", 12, T.RED,
               stop_r.centerx, stop_r.centery, anchor="center", uppercase=True)

        # ── Highway transparency slider (center) ──────────────────────────────
        sldr_x = stop_r.right + 20
        sldr_w = 220
        sldr_label_w = 38   # "HWY" label
        track_x = sldr_x + sldr_label_w + 8
        track_w = sldr_w - sldr_label_w - 8
        track_y = by + BTN_H // 2
        track_r = pygame.Rect(track_x, track_y - 4, track_w, 8)
        self._slider_track = track_r

        C.text(surf, "HWY", "cond_bold", 11, T.TEXT_3,
               sldr_x, track_y, anchor="midleft", uppercase=True)

        # Track background
        pygame.draw.rect(surf, T.HIGHWAY_GRID, track_r, border_radius=4)
        # Filled portion (alpha level)
        frac    = self._highway_alpha / 255
        fill_w  = max(8, int(track_w * frac))
        fill_r  = pygame.Rect(track_x, track_y - 4, fill_w, 8)
        col_hwy = T.GOLD if frac < 1.0 else T.TEXT_3
        pygame.draw.rect(surf, col_hwy, fill_r, border_radius=4)
        # Handle knob
        hx = track_x + int(track_w * frac)
        pygame.draw.circle(surf, T.TEXT_1, (hx, track_y), 7)
        pygame.draw.circle(surf, col_hwy, (hx, track_y), 5)
        # Percentage label
        pct_lbl = f"{int(frac * 100)}%"
        C.text(surf, pct_lbl, "cond_bold", 11, col_hwy,
               track_r.right + 6, track_y, anchor="midleft")

        # ── LYRICS toggle ─────────────────────────────────────────────────────
        lyr_on = self._lyrics_visible
        lyr_w  = 110
        lyr_r  = pygame.Rect(T.SCREEN_W - lyr_w - 10, by, lyr_w, BTN_H)
        self._lyr_btn = lyr_r
        pygame.draw.rect(surf, T.BG_CARD, lyr_r, border_radius=7)
        pygame.draw.rect(surf, T.SUCCESS if lyr_on else T.RED, lyr_r, 1, border_radius=7)
        C.text(surf, "LYRICS " + ("ON" if lyr_on else "OFF"), "cond_bold", 12,
               T.SUCCESS if lyr_on else T.RED,
               lyr_r.centerx, lyr_r.centery, anchor="center", uppercase=True)

    def _draw_notify(self, surf):
        """Brief toast notification for H/L/M toggles."""
        frac = min(1.0, self._notify_t)
        a    = int(min(255, frac * 500))
        bw, bh = 340, 36
        tx = T.SCREEN_W // 2 - bw // 2
        ty = T.HUD_H + 12
        bg = pygame.Surface((bw, bh), pygame.SRCALPHA)
        bg.fill((18, 18, 28, int(215 * frac)))
        pygame.draw.rect(bg, (*T.GOLD_DIM, int(170 * frac)),
                         bg.get_rect(), 1, border_radius=6)
        surf.blit(bg, (tx, ty))
        C.text(surf, self._notify_msg, "body_bold", 15, T.GOLD,
               T.SCREEN_W // 2, ty + bh // 2, anchor="center", alpha=a)

    def _draw_hint(self, surf):
        # Keyboard shortcut hints sit just below the bottom control strip
        parts = ["ESC Quit"]
        if self.audio.stems_loaded:
            parts += ["[ / ] Vocal", "M Mute"]
        C.text(surf, "  ·  ".join(parts), "body_reg", 11, T.TEXT_3,
               T.SCREEN_W // 2, T.HIGHWAY_BOT + 52, anchor="midtop")

    # ── Overlays ──────────────────────────────────────────────────────────

    def _draw_sep_toast(self, surf):
        """Slide-in toast: 'Vocal control ready — replay to use it'."""
        frac  = min(1.0, self._sep_toast_t)   # 1→0 as it fades
        a     = int(min(255, frac * 400))
        toast_w, toast_h = 460, 44
        tx = T.SCREEN_W // 2 - toast_w // 2
        ty = T.HUD_H + 16
        bg = pygame.Surface((toast_w, toast_h), pygame.SRCALPHA)
        bg.fill((30, 60, 30, int(200 * frac)))
        pygame.draw.rect(bg, (*T.SUCCESS, int(160 * frac)), bg.get_rect(), 1,
                         border_radius=6)
        surf.blit(bg, (tx, ty))
        C.text(surf, "Vocal control ready — replay song to use it",
               "body_semi", 15, T.SUCCESS,
               T.SCREEN_W // 2, ty + toast_h // 2, anchor="center", alpha=a)

    def _draw_countdown(self, surf):
        rem = -self._elapsed
        if rem <= 0: return
        n = int(math.ceil(rem))
        a = int(min(255,(1.0-(rem-int(rem)))*255+40))
        ov = pygame.Surface((T.SCREEN_W,T.SCREEN_H),pygame.SRCALPHA)
        ov.fill((0,0,0,110)); surf.blit(ov,(0,0))
        sc  = 1.0+0.45*(1.0-(rem-math.floor(rem)))
        sz  = int(108*sc)
        img = F.get("num_black",sz).render(str(n),True,T.GOLD)
        img.set_alpha(a)
        surf.blit(img,(T.SCREEN_W//2-img.get_width()//2,
                       T.SCREEN_H//2-img.get_height()//2))
        C.text(surf,self.song.title,"display_bold",28,T.TEXT_1,
               T.SCREEN_W//2,T.SCREEN_H//2+88,anchor="midtop")
        C.text(surf,self.song.artist,"body_reg",18,T.TEXT_3,
               T.SCREEN_W//2,T.SCREEN_H//2+124,anchor="midtop")
        if self._two:
            C.text(surf,"2-PLAYER MODE","cond_bold",14,T.INFO,
                   T.SCREEN_W//2,T.SCREEN_H//2+158,
                   anchor="midtop",uppercase=True)

    def _draw_pause(self, surf):
        ov=pygame.Surface((T.SCREEN_W,T.SCREEN_H),pygame.SRCALPHA)
        ov.fill((0,0,0,170)); surf.blit(ov,(0,0))
        C.text_shadow(surf,"PAUSED","display_black",80,T.GOLD,
                      T.SCREEN_W//2,T.SCREEN_H//2-44,anchor="center",
                      shadow_color=(0,0,0),offset=(4,4))
        C.text(surf,"P to continue  ·  ESC to quit",
               "body_reg",20,T.TEXT_3,
               T.SCREEN_W//2,T.SCREEN_H//2+52,anchor="midtop")
