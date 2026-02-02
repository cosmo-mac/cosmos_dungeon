"""Entry point for Cosmo's Dungeon — python3 -m game."""

import curses

from .dungeon import main

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    print("\nThanks for playing Cosmo's Dungeon!")
