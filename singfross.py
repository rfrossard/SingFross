#!/usr/bin/env python3
"""SingFross – Garage Band Karaoke  |  Entry point."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pygame, os
from ui import theme as T
from engine.mic_manager import MicManager
from engine import config as CFG

class Game:
    def __init__(self):
        pygame.init()
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()

        flags  = pygame.DOUBLEBUF | pygame.HWSURFACE
        self.screen = pygame.display.set_mode((T.SCREEN_W, T.SCREEN_H), flags)
        pygame.display.set_caption("SingFross – Garage Band Karaoke")
        self._set_icon()

        self.clock       = pygame.time.Clock()
        self.running     = True
        self.mic_manager = MicManager()
        self.mic_manager.start(CFG.get())

        self._screen_stack = []
        self.push_screen("menu")

    # Backwards-compat shim for any code still referencing pitch_detector
    @property
    def pitch_detector(self):
        return self.mic_manager

    def _set_icon(self):
        icon_path = os.path.join(os.path.dirname(__file__),
                                 "assets", "icon_32.png")
        try:
            icon = pygame.image.load(icon_path).convert_alpha()
        except Exception:
            icon = pygame.Surface((32, 32))
            icon.fill((8, 8, 10))
            pygame.draw.polygon(icon, (255, 200, 20), [
                (17, 2), (7, 14), (16, 14), (5, 30), (26, 12), (17, 12)])
        pygame.display.set_icon(icon)

    # ------------------------------------------------------------------ #
    # Screen management

    @property
    def current_screen(self):
        return self._screen_stack[-1] if self._screen_stack else None

    def push_screen(self, name: str):
        self._screen_stack.append(self._build_screen(name))

    def pop_screen(self):
        if len(self._screen_stack) > 1:
            self._screen_stack.pop()

    def go_home(self):
        """Clear the stack down to only the menu screen."""
        # Stop any playing audio before tearing down gameplay screens
        for s in self._screen_stack:
            if hasattr(s, "audio"):
                try:
                    s.audio.stop()
                    import pygame
                    pygame.mixer.music.set_endevent(0)
                except Exception:
                    pass
            if hasattr(s, "_video_cap") and s._video_cap:
                try:
                    s._video_cap.release()
                except Exception:
                    pass
        self._screen_stack = [self._build_screen("menu")]

    def replace_screen(self, name: str):
        if self._screen_stack:
            self._screen_stack.pop()
        self._screen_stack.append(self._build_screen(name))

    def _build_screen(self, name: str):
        if name == "menu":
            from screens.menu import MenuScreen
            return MenuScreen(self)
        elif name == "song_select":
            from screens.song_select import SongSelectScreen
            return SongSelectScreen(self)
        elif name == "settings":
            from screens.full_settings import SettingsScreen
            return SettingsScreen(self)
        elif name == "search":
            from screens.search_screen import SearchScreen
            return SearchScreen(self)
        elif name == "youtube_karaoke":
            from screens.youtube_karaoke import YoutubeKaraokeScreen
            return YoutubeKaraokeScreen(self)
        raise ValueError(f"Unknown screen: {name}")

    def start_song(self, song):
        from screens.gameplay import GameplayScreen
        self._screen_stack.append(GameplayScreen(self, song))

    def show_results(self, state, song):
        from screens.results import ResultsScreen
        self._screen_stack = [self._screen_stack[0],
                               ResultsScreen(self, state, song)]

    def quit(self):
        self.running = False

    # ------------------------------------------------------------------ #
    # Main loop

    def run(self):
        while self.running:
            dt = self.clock.tick(T.FPS) / 1000.0
            dt = min(dt, 0.05)   # cap at 50ms to avoid spiral of death

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    pygame.display.toggle_fullscreen()
                else:
                    if self.current_screen:
                        self.current_screen.handle_event(event)

            if self.current_screen:
                self.current_screen.update(dt)
                self.current_screen.draw(self.screen)

            pygame.display.flip()

        self.mic_manager.stop()
        pygame.quit()


if __name__ == "__main__":
    Game().run()
