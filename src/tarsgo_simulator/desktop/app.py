"""Minimal Pygame window used to prove the desktop entry point."""

import pygame


WINDOW_SIZE = (1024, 640)
BACKGROUND = (19, 25, 36)
FOREGROUND = (232, 238, 245)


def main() -> None:
    pygame.init()
    try:
        screen = pygame.display.set_mode(WINDOW_SIZE)
        pygame.display.set_caption("TARS-Go RoboMaster Tactical Simulator")
        font = pygame.font.Font(None, 42)
        clock = pygame.time.Clock()
        running = True

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            screen.fill(BACKGROUND)
            title = font.render("TARS-Go Tactical Simulator", True, FOREGROUND)
            subtitle = pygame.font.Font(None, 24).render(
                "V0 foundation — gameplay systems are not implemented yet",
                True,
                (165, 180, 198),
            )
            screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0] // 2, 285)))
            screen.blit(subtitle, subtitle.get_rect(center=(WINDOW_SIZE[0] // 2, 340)))
            pygame.display.flip()
            clock.tick(60)
    finally:
        pygame.quit()
