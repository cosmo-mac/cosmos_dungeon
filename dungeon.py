#!/usr/bin/env python3
"""Cosmo's Dungeon - A terminal roguelike dungeon crawler."""

import curses
import random
import sys
import time

# ── Tile characters ──────────────────────────────────────────────────────────
WALL = "#"
FLOOR = "."
DOOR = "+"
STAIRS = ">"
PLAYER = "@"
POTION = "!"
WEAPON = "/"
GOLD = "$"
SCROLL = "?"
MERCHANT = "M"

# ── Color pairs ──────────────────────────────────────────────────────────────
C_DEFAULT = 0
C_PLAYER = 1
C_WALL = 2
C_MONSTER = 3
C_ITEM = 4
C_GOLD = 5
C_UI = 6
C_STAIRS = 7
C_DANGER = 8
C_HEAL = 9
C_MERCHANT = 10

MONSTER_DEFS = [
    {"ch": "r", "name": "rat",         "hp": 6,  "atk": 2,  "xp": 5,  "color": C_MONSTER},
    {"ch": "s", "name": "snake",       "hp": 8,  "atk": 3,  "xp": 8,  "color": C_MONSTER},
    {"ch": "g", "name": "goblin",      "hp": 12, "atk": 4,  "xp": 12, "color": C_MONSTER},
    {"ch": "k", "name": "kobold",      "hp": 15, "atk": 5,  "xp": 16, "color": C_MONSTER},
    {"ch": "o", "name": "orc",         "hp": 22, "atk": 7,  "xp": 25, "color": C_DANGER},
    {"ch": "S", "name": "skeleton",    "hp": 20, "atk": 6,  "xp": 22, "color": C_DEFAULT},
    {"ch": "T", "name": "troll",       "hp": 35, "atk": 9,  "xp": 40, "color": C_DANGER},
    {"ch": "W", "name": "wraith",      "hp": 28, "atk": 11, "xp": 50, "color": C_DANGER},
    {"ch": "D", "name": "dragon",      "hp": 60, "atk": 15, "xp": 100,"color": C_DANGER},
]

WEAPON_NAMES = [
    ("rusty dagger",   2),
    ("short sword",    4),
    ("mace",           6),
    ("long sword",     8),
    ("battle axe",    10),
    ("war hammer",    12),
    ("enchanted blade",15),
]

SCROLL_EFFECTS = [
    ("fireball",    "damage"),
    ("lightning",   "damage"),
    ("healing",     "heal"),
    ("strength",    "buff_atk"),
    ("shield",      "buff_def"),
    ("mapping",     "reveal"),
]

SCROLL_DESCS = {
    "damage": "damages all visible enemies",
    "heal":   "fully restores HP",
    "buff_atk": "+2 ATK permanently",
    "buff_def": "+2 DEF permanently",
    "reveal": "reveals dungeon map",
}


def _item_desc(kind, value):
    """Return a short description string for a weapon or scroll."""
    if kind == "weapon":
        return f"(ATK +{value})"
    if kind == "scroll":
        effect_type = value[1] if isinstance(value, (tuple, list)) else value
        return f"({SCROLL_DESCS.get(effect_type, '')})"
    return ""


def _generate_merchant_stock(depth):
    """Build a fixed shop inventory for a merchant on this depth."""
    stock = []
    # 1-2 potions
    for _ in range(random.randint(1, 2)):
        heal = random.randint(10, 20) + depth * 2
        price = random.randint(15, 25)
        stock.append({"ch": POTION, "name": f"potion (+{heal} HP)", "color": C_HEAL,
                       "kind": "potion", "value": heal, "price": price})
    # 1 weapon
    tier = min(random.randint(0, depth + 1), len(WEAPON_NAMES) - 1)
    name, bonus = WEAPON_NAMES[tier]
    price = 20 + bonus * 3
    stock.append({"ch": WEAPON, "name": name, "color": C_ITEM,
                   "kind": "weapon", "value": bonus, "price": price})
    # 1-2 scrolls
    for _ in range(random.randint(1, 2)):
        effect = random.choice(SCROLL_EFFECTS)
        price = random.randint(30, 50)
        stock.append({"ch": SCROLL, "name": f"scroll of {effect[0]}", "color": C_ITEM,
                       "kind": "scroll", "value": effect, "price": price})
    return stock


class Entity:
    def __init__(self, x, y, ch, name, color, **kw):
        self.x, self.y = x, y
        self.ch = ch
        self.name = name
        self.color = color
        for k, v in kw.items():
            setattr(self, k, v)


class Player(Entity):
    def __init__(self, x, y):
        super().__init__(x, y, PLAYER, "you", C_PLAYER)
        self.max_hp = 30
        self.hp = 30
        self.base_atk = 3
        self.atk_bonus = 0
        self.defense = 0
        self.xp = 0
        self.level = 1
        self.gold = 0
        self.weapon = "fists"
        self.kills = 0
        self.depth = 1
        self.max_depth = 1
        self.inventory = []

    @property
    def atk(self):
        return self.base_atk + self.atk_bonus

    def xp_to_next(self):
        return self.level * 20

    def gain_xp(self, amount):
        self.xp += amount
        leveled = False
        while self.xp >= self.xp_to_next():
            self.xp -= self.xp_to_next()
            self.level += 1
            self.max_hp += 8
            self.hp = self.max_hp
            self.base_atk += 1
            leveled = True
        return leveled


class DungeonLevel:
    def __init__(self, width, height, depth):
        self.w = width
        self.h = height
        self.depth = depth
        self.tiles = [[WALL] * width for _ in range(height)]
        self.revealed = [[False] * width for _ in range(height)]
        self.visible = [[False] * width for _ in range(height)]
        self.rooms = []
        self.monsters = []
        self.items = []
        self.stairs_pos = None
        self.merchant = None
        self._generate()

    def _generate(self):
        num_rooms = random.randint(5, 9)
        for _ in range(200):
            if len(self.rooms) >= num_rooms:
                break
            rw = random.randint(5, 12)
            rh = random.randint(4, 8)
            rx = random.randint(1, self.w - rw - 2)
            ry = random.randint(1, self.h - rh - 2)
            room = (rx, ry, rw, rh)
            if not any(self._rooms_overlap(room, r) for r in self.rooms):
                self._carve_room(room)
                if self.rooms:
                    self._connect(self.rooms[-1], room)
                self.rooms.append(room)

        # Place stairs in last room
        lr = self.rooms[-1]
        sx = lr[0] + lr[2] // 2
        sy = lr[1] + lr[3] // 2
        self.tiles[sy][sx] = STAIRS
        self.stairs_pos = (sx, sy)

        # Place monsters
        for room in self.rooms[1:]:
            n = random.randint(0, 2 + self.depth // 2)
            for _ in range(n):
                mx = random.randint(room[0] + 1, room[0] + room[2] - 2)
                my = random.randint(room[1] + 1, room[1] + room[3] - 2)
                if self.tiles[my][mx] == FLOOR:
                    tier = min(random.randint(0, self.depth), len(MONSTER_DEFS) - 1)
                    md = MONSTER_DEFS[tier]
                    # Scale HP/ATK slightly with depth
                    hp_scale = 1 + (self.depth - 1) * 0.15
                    atk_scale = 1 + (self.depth - 1) * 0.1
                    m = Entity(mx, my, md["ch"], md["name"], md["color"],
                               hp=int(md["hp"] * hp_scale),
                               max_hp=int(md["hp"] * hp_scale),
                               atk=int(md["atk"] * atk_scale),
                               xp=md["xp"])
                    self.monsters.append(m)

        # Place items
        for room in self.rooms:
            if random.random() < 0.5:
                ix = random.randint(room[0] + 1, room[0] + room[2] - 2)
                iy = random.randint(room[1] + 1, room[1] + room[3] - 2)
                if self.tiles[iy][ix] == FLOOR:
                    self._place_item(ix, iy)

        # Place merchant in a random middle room (not first or last)
        if len(self.rooms) > 2:
            mroom = random.choice(self.rooms[1:-1])
            mx = mroom[0] + mroom[2] // 2
            my = mroom[1] + mroom[3] // 2
            self.merchant = Entity(mx, my, MERCHANT, "merchant", C_MERCHANT,
                                   stock=_generate_merchant_stock(self.depth))

    def _place_item(self, x, y):
        roll = random.random()
        if roll < 0.35:
            heal = random.randint(8, 20)
            self.items.append(Entity(x, y, POTION, f"potion (+{heal} HP)", C_HEAL, kind="potion", value=heal))
        elif roll < 0.6:
            tier = min(random.randint(0, self.depth), len(WEAPON_NAMES) - 1)
            name, bonus = WEAPON_NAMES[tier]
            self.items.append(Entity(x, y, WEAPON, name, C_ITEM, kind="weapon", value=bonus))
        elif roll < 0.85:
            amount = random.randint(5, 15 + self.depth * 5)
            self.items.append(Entity(x, y, GOLD, f"{amount} gold", C_GOLD, kind="gold", value=amount))
        else:
            effect = random.choice(SCROLL_EFFECTS)
            self.items.append(Entity(x, y, SCROLL, f"scroll of {effect[0]}", C_ITEM, kind="scroll", value=effect))

    def _rooms_overlap(self, a, b):
        return not (a[0] + a[2] + 1 < b[0] or b[0] + b[2] + 1 < a[0] or
                    a[1] + a[3] + 1 < b[1] or b[1] + b[3] + 1 < a[1])

    def _carve_room(self, room):
        rx, ry, rw, rh = room
        for y in range(ry, ry + rh):
            for x in range(rx, rx + rw):
                self.tiles[y][x] = FLOOR

    def _connect(self, r1, r2):
        x1 = r1[0] + r1[2] // 2
        y1 = r1[1] + r1[3] // 2
        x2 = r2[0] + r2[2] // 2
        y2 = r2[1] + r2[3] // 2
        x, y = x1, y1
        while x != x2:
            self.tiles[y][x] = FLOOR
            x += 1 if x2 > x else -1
        while y != y2:
            self.tiles[y][x] = FLOOR
            y += 1 if y2 > y else -1

    def monster_at(self, x, y):
        for m in self.monsters:
            if m.x == x and m.y == y:
                return m
        return None

    def item_at(self, x, y):
        for i in self.items:
            if i.x == x and i.y == y:
                return i
        return None

    def is_walkable(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.tiles[y][x] != WALL
        return False

    def compute_fov(self, px, py, radius=6):
        import math
        for row in self.visible:
            for i in range(len(row)):
                row[i] = False
        for angle_step in range(360):
            angle = angle_step * math.pi / 180
            dx = math.cos(angle)
            dy = math.sin(angle)
            x, y = float(px), float(py)
            for _ in range(radius):
                ix, iy = int(round(x)), int(round(y))
                if 0 <= ix < self.w and 0 <= iy < self.h:
                    self.visible[iy][ix] = True
                    self.revealed[iy][ix] = True
                    if self.tiles[iy][ix] == WALL:
                        break
                else:
                    break
                x += dx
                y += dy

    def reveal_all(self):
        for y in range(self.h):
            for x in range(self.w):
                self.revealed[y][x] = True


class Game:
    MAP_W = 70
    MAP_H = 22

    def __init__(self, stdscr):
        self.scr = stdscr
        self.running = True
        self.messages = []
        self.player = Player(0, 0)
        self.dungeon = None
        self.state = "title"
        self._shop_stock = []
        self._init_colors()
        curses.curs_set(0)
        self.scr.nodelay(False)
        self.scr.keypad(True)

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(C_PLAYER, curses.COLOR_CYAN, -1)
        curses.init_pair(C_WALL, curses.COLOR_WHITE, -1)
        curses.init_pair(C_MONSTER, curses.COLOR_RED, -1)
        curses.init_pair(C_ITEM, curses.COLOR_MAGENTA, -1)
        curses.init_pair(C_GOLD, curses.COLOR_YELLOW, -1)
        curses.init_pair(C_UI, curses.COLOR_WHITE, -1)
        curses.init_pair(C_STAIRS, curses.COLOR_GREEN, -1)
        curses.init_pair(C_DANGER, curses.COLOR_RED, -1)
        curses.init_pair(C_HEAL, curses.COLOR_GREEN, -1)
        curses.init_pair(C_MERCHANT, curses.COLOR_YELLOW, -1)

    def msg(self, text):
        self.messages.append(text)
        if len(self.messages) > 5:
            self.messages.pop(0)

    def new_level(self, depth):
        self.dungeon = DungeonLevel(self.MAP_W, self.MAP_H, depth)
        self.player.depth = depth
        self.player.max_depth = max(self.player.max_depth, depth)
        # Place player in first room
        r = self.dungeon.rooms[0]
        self.player.x = r[0] + r[2] // 2
        self.player.y = r[1] + r[3] // 2
        self.dungeon.compute_fov(self.player.x, self.player.y)
        self.msg(f"You descend to depth {depth}.")

    def run(self):
        while self.running:
            if self.state == "title":
                self._title_screen()
            elif self.state == "play":
                self._draw()
                self._handle_input()
            elif self.state == "dead":
                self._death_screen()
            elif self.state == "inventory":
                self._inventory_screen()
            elif self.state == "shop":
                self._shop_screen()
            elif self.state == "win":
                self._win_screen()

    # ── Title screen ─────────────────────────────────────────────────────────
    def _title_screen(self):
        self.scr.clear()
        h, w = self.scr.getmaxyx()
        title = [
            "  ___                       _        ",
            " / __|___ ___ _ __  ___  _( )___     ",
            "| (__/ _ (_-<| '  \\/ _ \\(_)/(_-<     ",
            " \\___\\___/__/|_|_|_\\___/   /__/      ",
            "                                     ",
            " ___                                  ",
            "|   \\ _  _ _ _  __ _ ___ ___ _ _      ",
            "| |) | || | ' \\/ _` / -_) _ \\ ' \\    ",
            "|___/ \\_,_|_||_\\__, \\___\\___/_||_|   ",
            "               |___/                  ",
        ]
        start_y = max(0, h // 2 - 8)
        for i, line in enumerate(title):
            x = max(0, w // 2 - len(line) // 2)
            if start_y + i < h:
                try:
                    self.scr.addstr(start_y + i, x, line,
                                    curses.color_pair(C_PLAYER) | curses.A_BOLD)
                except curses.error:
                    pass

        instructions = [
            "",
            "A roguelike dungeon crawler",
            "",
            "Move: arrow keys / WASD / hjkl",
            "Inventory: i    Stairs: > or ENTER",
            "Wait: .  or  5     Quit: q",
            "",
            "Press any key to begin...",
        ]
        for i, line in enumerate(instructions):
            x = max(0, w // 2 - len(line) // 2)
            row = start_y + len(title) + i
            if row < h:
                try:
                    self.scr.addstr(row, x, line, curses.color_pair(C_UI))
                except curses.error:
                    pass

        self.scr.refresh()
        self.scr.getch()
        self.state = "play"
        self.player = Player(0, 0)
        self.messages = []
        self.new_level(1)

    # ── Drawing ──────────────────────────────────────────────────────────────
    def _draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        d = self.dungeon

        # Offset to center map
        ox = max(0, (w - self.MAP_W) // 2)
        oy = 1

        # Draw map
        for y in range(min(self.MAP_H, h - 4)):
            for x in range(min(self.MAP_W, w - ox)):
                if d.visible[y][x]:
                    tile = d.tiles[y][x]
                    color = C_WALL
                    attr = 0
                    if tile == STAIRS:
                        color = C_STAIRS
                        attr = curses.A_BOLD
                    elif tile == FLOOR:
                        color = C_DEFAULT
                    try:
                        self.scr.addstr(oy + y, ox + x, tile,
                                        curses.color_pair(color) | attr)
                    except curses.error:
                        pass
                elif d.revealed[y][x]:
                    tile = d.tiles[y][x]
                    try:
                        self.scr.addstr(oy + y, ox + x, tile,
                                        curses.color_pair(C_WALL) | curses.A_DIM)
                    except curses.error:
                        pass

        # Draw items
        for item in d.items:
            if d.visible[item.y][item.x]:
                try:
                    self.scr.addstr(oy + item.y, ox + item.x, item.ch,
                                    curses.color_pair(item.color) | curses.A_BOLD)
                except curses.error:
                    pass

        # Draw monsters
        for m in d.monsters:
            if d.visible[m.y][m.x]:
                try:
                    self.scr.addstr(oy + m.y, ox + m.x, m.ch,
                                    curses.color_pair(m.color) | curses.A_BOLD)
                except curses.error:
                    pass

        # Draw merchant
        if d.merchant and d.visible[d.merchant.y][d.merchant.x]:
            try:
                self.scr.addstr(oy + d.merchant.y, ox + d.merchant.x,
                                d.merchant.ch,
                                curses.color_pair(C_MERCHANT) | curses.A_BOLD)
            except curses.error:
                pass

        # Draw player
        try:
            self.scr.addstr(oy + self.player.y, ox + self.player.x, PLAYER,
                            curses.color_pair(C_PLAYER) | curses.A_BOLD)
        except curses.error:
            pass

        # ── Status bar ───────────────────────────────────────────────────────
        bar_y = oy + self.MAP_H + 1
        p = self.player
        hp_bar_len = 15
        hp_filled = max(0, int(hp_bar_len * p.hp / p.max_hp))
        hp_bar = "\u2588" * hp_filled + "\u2591" * (hp_bar_len - hp_filled)
        hp_color = C_HEAL if p.hp > p.max_hp * 0.3 else C_DANGER

        status = (f" HP [{hp_bar}] {p.hp}/{p.max_hp}  ATK:{p.atk}  DEF:{p.defense}"
                  f"  LVL:{p.level}  XP:{p.xp}/{p.xp_to_next()}  Gold:{p.gold}"
                  f"  Depth:{p.depth}  Weapon:{p.weapon} ")
        if bar_y < h:
            try:
                self.scr.addstr(bar_y, 0, status[:w - 1],
                                curses.color_pair(hp_color) | curses.A_BOLD)
            except curses.error:
                pass

        # ── Messages ─────────────────────────────────────────────────────────
        msg_y = 0
        if self.messages and msg_y < h:
            line = " | ".join(self.messages[-3:])
            try:
                self.scr.addstr(msg_y, 0, line[:w - 1], curses.color_pair(C_UI))
            except curses.error:
                pass

        self.scr.refresh()

    # ── Input ────────────────────────────────────────────────────────────────
    def _handle_input(self):
        key = self.scr.getch()
        dx, dy = 0, 0

        # Movement
        if key in (curses.KEY_UP, ord("w"), ord("k")):
            dy = -1
        elif key in (curses.KEY_DOWN, ord("s"), ord("j")):
            dy = 1
        elif key in (curses.KEY_LEFT, ord("a"), ord("h")):
            dx = -1
        elif key in (curses.KEY_RIGHT, ord("d"), ord("l")):
            dx = 1
        elif key in (ord("y"),):
            dx, dy = -1, -1
        elif key in (ord("u"),):
            dx, dy = 1, -1
        elif key in (ord("b"),):
            dx, dy = -1, 1
        elif key in (ord("n"),):
            dx, dy = 1, 1
        elif key in (ord(">"), ord("\n"), curses.KEY_ENTER):
            self._try_descend()
            return
        elif key == ord(".") or key == ord("5"):
            pass  # Wait
        elif key == ord("i"):
            self.state = "inventory"
            return
        elif key == ord("q"):
            self.running = False
            return
        else:
            return

        if dx != 0 or dy != 0:
            self._try_move(dx, dy)

        self._monster_turns()

    def _try_move(self, dx, dy):
        nx = self.player.x + dx
        ny = self.player.y + dy
        d = self.dungeon

        # Bump into merchant?
        if d.merchant and d.merchant.x == nx and d.merchant.y == ny:
            self._shop_stock = d.merchant.stock
            self.state = "shop"
            return

        # Attack monster?
        mon = d.monster_at(nx, ny)
        if mon:
            self._attack_monster(mon)
            return

        if d.is_walkable(nx, ny):
            self.player.x = nx
            self.player.y = ny
            d.compute_fov(nx, ny)
            # Pick up items
            item = d.item_at(nx, ny)
            if item:
                self._pickup(item)

    def _attack_monster(self, mon):
        p = self.player
        dmg = max(1, p.atk - random.randint(0, 2))
        mon.hp -= dmg
        if mon.hp <= 0:
            self.msg(f"You slay the {mon.name}! (+{mon.xp} XP)")
            self.dungeon.monsters.remove(mon)
            p.kills += 1
            if p.gain_xp(mon.xp):
                self.msg(f"Level up! You are now level {p.level}!")
            # Check win condition
            if mon.name == "dragon" and self.player.depth >= 8:
                self.state = "win"
        else:
            self.msg(f"You hit the {mon.name} for {dmg} dmg. ({mon.hp}/{mon.max_hp})")

    def _pickup(self, item):
        p = self.player
        if item.kind == "potion":
            p.inventory.append(item)
            self.msg(f"Picked up {item.name}. (i to use)")
        elif item.kind == "weapon":
            if item.value > p.atk_bonus:
                p.weapon = item.name
                p.atk_bonus = item.value
                self.msg(f"Equipped {item.name}! (ATK +{item.value})")
            else:
                self.msg(f"The {item.name} is weaker than your {p.weapon}.")
        elif item.kind == "gold":
            p.gold += item.value
            self.msg(f"Found {item.value} gold! (Total: {p.gold})")
        elif item.kind == "scroll":
            p.inventory.append(item)
            self.msg(f"Picked up {item.name}. (i to use)")
        self.dungeon.items.remove(item)

    def _try_descend(self):
        p = self.player
        if (self.dungeon.stairs_pos
                and p.x == self.dungeon.stairs_pos[0]
                and p.y == self.dungeon.stairs_pos[1]):
            self.new_level(p.depth + 1)
        else:
            self.msg("There are no stairs here.")

    # ── Monster AI ───────────────────────────────────────────────────────────
    def _monster_turns(self):
        p = self.player
        d = self.dungeon
        for m in list(d.monsters):
            if not d.visible[m.y][m.x]:
                continue
            dist = abs(m.x - p.x) + abs(m.y - p.y)
            if dist <= 1:
                dmg = max(1, m.atk - p.defense - random.randint(0, 2))
                p.hp -= dmg
                self.msg(f"The {m.name} hits you for {dmg}!")
                if p.hp <= 0:
                    self.state = "dead"
                    return
            elif dist <= 8:
                dx = (1 if p.x > m.x else -1) if p.x != m.x else 0
                dy = (1 if p.y > m.y else -1) if p.y != m.y else 0
                if dx != 0 and d.is_walkable(m.x + dx, m.y) and not d.monster_at(m.x + dx, m.y):
                    m.x += dx
                elif dy != 0 and d.is_walkable(m.x, m.y + dy) and not d.monster_at(m.x, m.y + dy):
                    m.y += dy

    # ── Inventory ────────────────────────────────────────────────────────────
    def _inventory_screen(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        p = self.player

        try:
            self.scr.addstr(1, 2, "=== INVENTORY ===",
                            curses.color_pair(C_UI) | curses.A_BOLD)
        except curses.error:
            pass

        if not p.inventory:
            try:
                self.scr.addstr(3, 4, "Your pack is empty.",
                                curses.color_pair(C_UI))
            except curses.error:
                pass
        else:
            for i, item in enumerate(p.inventory):
                letter = chr(ord("a") + i)
                try:
                    self.scr.addstr(3 + i, 4, f"[{letter}] {item.ch} {item.name}",
                                    curses.color_pair(item.color))
                except curses.error:
                    pass

        try:
            self.scr.addstr(h - 2, 2, "Press a letter to use, ESC/i to close",
                            curses.color_pair(C_UI))
        except curses.error:
            pass

        self.scr.refresh()
        key = self.scr.getch()

        if key == 27 or key == ord("i"):
            self.state = "play"
        elif ord("a") <= key <= ord("z"):
            idx = key - ord("a")
            if idx < len(p.inventory):
                self._use_item(idx)
                self.state = "play"

    def _use_item(self, idx):
        p = self.player
        item = p.inventory[idx]
        if item.kind == "potion":
            heal = item.value
            p.hp = min(p.max_hp, p.hp + heal)
            self.msg(f"You drink the potion. (+{heal} HP, now {p.hp}/{p.max_hp})")
        elif item.kind == "scroll":
            name, effect = item.value
            if effect == "damage":
                total = 0
                for m in list(self.dungeon.monsters):
                    if self.dungeon.visible[m.y][m.x]:
                        dmg = random.randint(10, 25)
                        m.hp -= dmg
                        total += 1
                        if m.hp <= 0:
                            self.dungeon.monsters.remove(m)
                            p.kills += 1
                            p.gain_xp(m.xp)
                self.msg(f"The scroll of {name} blasts {total} creatures!")
            elif effect == "heal":
                p.hp = p.max_hp
                self.msg("The scroll fully restores your health!")
            elif effect == "buff_atk":
                p.base_atk += 2
                self.msg(f"You feel stronger! (ATK now {p.atk})")
            elif effect == "buff_def":
                p.defense += 2
                self.msg(f"A magical shield surrounds you! (DEF now {p.defense})")
            elif effect == "reveal":
                self.dungeon.reveal_all()
                self.msg("The dungeon layout is revealed!")
        p.inventory.pop(idx)

    # ── Shop ─────────────────────────────────────────────────────────────────
    def _shop_screen(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        p = self.player

        try:
            self.scr.addstr(1, 2, "=== MERCHANT'S SHOP ===",
                            curses.color_pair(C_MERCHANT) | curses.A_BOLD)
            self.scr.addstr(2, 2, f"Your gold: {p.gold}",
                            curses.color_pair(C_GOLD) | curses.A_BOLD)
        except curses.error:
            pass

        for i, entry in enumerate(self._shop_stock):
            letter = chr(ord("a") + i)
            desc = _item_desc(entry["kind"], entry["value"])
            line = f"[{letter}] {entry['ch']} {entry['name']}  {desc}  - {entry['price']}g"
            color = C_UI if p.gold >= entry["price"] else C_DANGER
            try:
                self.scr.addstr(4 + i, 4, line, curses.color_pair(color))
            except curses.error:
                pass

        try:
            self.scr.addstr(h - 2, 2, "Press a letter to buy, ESC to leave",
                            curses.color_pair(C_UI))
        except curses.error:
            pass

        self.scr.refresh()
        key = self.scr.getch()

        if key == 27:
            self.state = "play"
        elif ord("a") <= key <= ord("z"):
            idx = key - ord("a")
            if idx < len(self._shop_stock):
                entry = self._shop_stock[idx]
                price = entry["price"]
                if p.gold >= price:
                    p.gold -= price
                    if entry["kind"] == "weapon":
                        if entry["value"] > p.atk_bonus:
                            p.weapon = entry["name"]
                            p.atk_bonus = entry["value"]
                            self.msg(f"Bought and equipped {entry['name']}!")
                        else:
                            self.msg(f"Bought {entry['name']} but your {p.weapon} is better.")
                    else:
                        item = Entity(0, 0, entry["ch"], entry["name"],
                                      entry["color"],
                                      kind=entry["kind"], value=entry["value"])
                        p.inventory.append(item)
                        self.msg(f"Bought {entry['name']}.")
                    self._shop_stock.pop(idx)
                else:
                    self.msg("You can't afford that!")

    # ── Death screen ─────────────────────────────────────────────────────────
    def _death_screen(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        p = self.player

        lines = [
            "  _____  _____  _____  ",
            " |  __ \\|_   _||  __ \\ ",
            " | |__) | | |  | |__) |",
            " |  _  /  | |  |  ___/ ",
            " | | \\ \\ _| |_ | |     ",
            " |_|  \\_\\_____||_|     ",
            "",
            "YOU HAVE PERISHED",
            "",
            f"Level: {p.level}   Depth: {p.max_depth}   Kills: {p.kills}   Gold: {p.gold}",
            "",
            "Press SPACE to try again, Q to quit",
        ]

        sy = max(0, h // 2 - len(lines) // 2)
        for i, line in enumerate(lines):
            x = max(0, w // 2 - len(line) // 2)
            row = sy + i
            if row < h:
                color = C_DANGER if i < 6 else C_UI
                try:
                    self.scr.addstr(row, x, line,
                                    curses.color_pair(color) | curses.A_BOLD)
                except curses.error:
                    pass

        self.scr.refresh()
        key = self.scr.getch()
        if key == ord("q"):
            self.running = False
        elif key == ord(" "):
            self.state = "title"

    # ── Win screen ───────────────────────────────────────────────────────────
    def _win_screen(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        p = self.player

        lines = [
            " __     _____ _____ _____ ___  ______   __",
            " \\ \\   / /_ _/ ____|_   _/ _ \\|  _ \\ \\ / /",
            "  \\ \\ / / | | |      | || | | | |_) \\ V / ",
            "   \\ V /  | | |      | || | | |  _ < \\ /  ",
            "    \\ /  _| | |____ _| || |_| | | \\ \\ |   ",
            "     \\/  |___|_____|_____\\___/|_|  \\_\\|   ",
            "",
            "THE DRAGON IS SLAIN!",
            "You have conquered Cosmo's Dungeon!",
            "",
            f"Level: {p.level}   Max Depth: {p.max_depth}   Kills: {p.kills}   Gold: {p.gold}",
            "",
            f"Final Score: {p.kills * 10 + p.gold + p.max_depth * 50 + p.level * 25}",
            "",
            "Press SPACE to play again, Q to quit",
        ]

        sy = max(0, h // 2 - len(lines) // 2)
        for i, line in enumerate(lines):
            x = max(0, w // 2 - len(line) // 2)
            row = sy + i
            if row < h:
                color = C_GOLD if i < 6 else C_UI
                try:
                    self.scr.addstr(row, x, line,
                                    curses.color_pair(color) | curses.A_BOLD)
                except curses.error:
                    pass

        self.scr.refresh()
        key = self.scr.getch()
        if key == ord("q"):
            self.running = False
        elif key == ord(" "):
            self.state = "title"


def main(stdscr):
    game = Game(stdscr)
    game.run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    print("\nThanks for playing Cosmo's Dungeon!")
