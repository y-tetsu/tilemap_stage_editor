import pygame
import sys
import json
import os
from tkinter import Tk, filedialog, simpledialog, Toplevel, StringVar, OptionMenu, Button, Label

# initialize tkinter for file dialogs (no window)
root = Tk()
root.withdraw()

pygame.init()

# --- Config (keep consistent with your earlier working settings) ---
DEFAULT_SCREEN_WIDTH, DEFAULT_SCREEN_HEIGHT = 1300, 800
TILE_SIZE = 8

# Palette (fixed)
PALETTE_TILE_SCALE = 4   # 原寸4倍（あなたの要望）
PALETTE_COLS = 10
PALETTE_TILE_SIZE = TILE_SIZE * PALETTE_TILE_SCALE
PALETTE_PADDING = 10
PALETTE_SPACING = 4
PALETTE_PANEL_WIDTH = PALETTE_PADDING * 2 + PALETTE_COLS * (PALETTE_TILE_SIZE + PALETTE_SPACING)

# Stage layout
STAGE_OFFSET_X = PALETTE_PANEL_WIDTH + 20
STAGE_OFFSET_Y = 40
SCROLLBAR_SIZE = 14
MIN_VIEW = 64

# Window
screen = pygame.display.set_mode((DEFAULT_SCREEN_WIDTH, DEFAULT_SCREEN_HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Tilemap Editor")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 20)

# --- State ---
tileset = None
tiles = []
palette_scroll = 0

map_width, map_height = 32, 30
map_data = []
# -1 means no selection / empty. Start with no tile selected.
selected_tile = -1

stage_zoom = 3
stage_scroll_x = 0.0   # negative or zero: offset applied when drawing tiles: draw_x = x*tile_px + stage_scroll_x
stage_scroll_y = 0.0

left_down = False
right_down = False

# --- Copy/paste selection state (new) ---
copy_selecting = False     # True while right-button dragging selection
# Project / multi-stage state
project = None
project_path = None
stage_names = []
current_stage = None

# Copy/paste buffers and preview state
copy_buffer = None
paste_preview_active = False
paste_preview_pos = None
copy_start = None
copy_end = None

def select_stage_dialog():
    """Blocking stage selection using simpledialog.askstring (reliable).
    Updates globals: current_stage, map_data, map_width, map_height."""
    global project, current_stage, map_data, map_width, map_height, stage_names
    print('select_stage_dialog called; project loaded=', bool(project))
    if project is None:
        print('No project loaded')
        return
    # ensure stage_names populated
    if not stage_names:
        stage_names[:] = list(project.get('maps', {}).keys())
    prompt = 'Available stages:\n' + '\n'.join(stage_names) + '\n\nEnter stage name:'
    name = simpledialog.askstring('Select Stage', prompt)
    if not name:
        return
    if name not in project.get('maps', {}):
        print('Stage not found:', name)
        return
    current_stage = name
    m = project['maps'][current_stage]
    map_data = [list(row) for row in m]
    map_height = len(map_data)
    map_width = len(map_data[0]) if map_height else 0
    print('Switched to stage', current_stage)

def rename_current_stage(new_name):
    global project, current_stage, stage_names
    if project is None:
        print('No project loaded')
        return False
    if not new_name or new_name == current_stage:
        return False
    if new_name in project['maps']:
        print('Stage name already exists:', new_name)
        return False
    # rename in maps
    project['maps'][new_name] = project['maps'].pop(current_stage)
    # rename check_points and sprites if present
    for key in ('check_points','sprites'):
        if key in project and isinstance(project[key], dict):
            if current_stage in project[key]:
                project[key][new_name] = project[key].pop(current_stage)
    # update initial_map if needed
    if project.get('initial_map') == current_stage:
        project['initial_map'] = new_name
    # update current_stage and stage_names
    idx = stage_names.index(current_stage) if current_stage in stage_names else None
    current_stage = new_name
    if idx is not None:
        stage_names[idx] = new_name
    else:
        stage_names = list(project['maps'].keys())
    print('Renamed stage to', new_name)
    return True

def prompt_rename_stage():
    if project is None:
        print('No project loaded')
        return
    new = simpledialog.askstring('Rename Stage', f'New name for stage "{current_stage}":')
    if new:
        rename_current_stage(new)

def resize_current_stage(new_w, new_h):
    global map_data, map_width, map_height
    if map_data is None:
        return
    old_h = len(map_data)
    old_w = len(map_data[0]) if old_h else 0
    new_data = [[-1 for _ in range(new_w)] for _ in range(new_h)]
    for y in range(min(old_h, new_h)):
        for x in range(min(old_w, new_w)):
            new_data[y][x] = map_data[y][x]
    map_data = new_data
    map_width = new_w
    map_height = new_h
    print(f'Resized stage to {new_w}x{new_h} (data preserved in top-left)')

def prompt_resize_stage():
    if project is None:
        print('No project loaded')
        return
    w = simpledialog.askinteger('Resize Stage', 'New width:', initialvalue=map_width, minvalue=1)
    h = simpledialog.askinteger('Resize Stage', 'New height:', initialvalue=map_height, minvalue=1)
    if w and h:
        resize_current_stage(w, h)

# --- File dialogs ---
def open_file_dialog_png():
    return filedialog.askopenfilename(title='Select tileset image', filetypes=[('PNG','*.png'),('All files','*.*')])

def open_file_dialog_json():
    return filedialog.askopenfilename(title='Open map JSON', filetypes=[('JSON','*.json'),('All files','*.*')])

def save_file_dialog_json():
    return filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON','*.json'),('All files','*.*')])


def load_project_json(path=None):
    """Load a multi-stage project JSON. Sets `project`, `project_path`, `stage_names`,
    `current_stage` and loads `map_data` for the selected stage."""
    global project, project_path, stage_names, current_stage, map_data, map_width, map_height
    if path is None:
        path = open_file_dialog_json()
    if not path:
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            obj = json.load(f)
    except Exception as e:
        print('Failed to load project JSON:', e)
        return
    project = obj
    project_path = path
    maps = project.get('maps', {})
    stage_names = list(maps.keys())
    # prefer initial_map if present
    initial = project.get('initial_map')
    if initial in maps:
        current_stage = initial
    else:
        current_stage = stage_names[0] if stage_names else None
    if current_stage:
        m = maps[current_stage]
        map_data = [list(row) for row in m]
        map_height = len(map_data)
        map_width = len(map_data[0]) if map_height else 0
    print('Loaded project', path, 'stages:', len(stage_names))


def save_project_json(path=None):
    """Save current `project` (ensuring current stage map is written)."""
    global project, project_path, current_stage, map_data
    if project is None:
        project = {}
    project.setdefault('maps', {})
    if current_stage:
        # store a copy of map_data
        project['maps'][current_stage] = [list(row) for row in map_data]
    if path is None:
        path = save_file_dialog_json()
    if not path:
        return
    try:
        # create backup if file exists
        if os.path.exists(path):
            bak = path + '.bak'
            try:
                os.replace(path, bak)
            except Exception:
                pass
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(project, f, indent=2, ensure_ascii=False)
        project_path = path
        print('Saved project to', path)
    except Exception as e:
        print('Failed to save project:', e)

# --- Tile / map helpers ---
def load_tileset(path=None):
    global tileset, tiles, selected_tile
    if path is None:
        path = open_file_dialog_png()
    if not path:
        return False
    try:
        tileset = pygame.image.load(path).convert_alpha()
    except Exception as e:
        print('Failed to load tileset:', e)
        return False
    tiles.clear()
    cols = tileset.get_width() // TILE_SIZE
    rows = tileset.get_height() // TILE_SIZE
    for ry in range(rows):
        for rx in range(cols):
            rect = pygame.Rect(rx * TILE_SIZE, ry * TILE_SIZE, TILE_SIZE, TILE_SIZE)
            tiles.append(tileset.subsurface(rect).copy())
    # keep no selection after loading tileset; user must click to select
    selected_tile = -1
    print(f'Loaded tileset: {path} ({len(tiles)} tiles)')
    return True

def new_map(w=None, h=None):
    global map_width, map_height, map_data, stage_scroll_x, stage_scroll_y
    if w is None or h is None:
        w = simpledialog.askinteger('New Map', 'Width:', initialvalue=map_width, minvalue=1)
        h = simpledialog.askinteger('New Map', 'Height:', initialvalue=map_height, minvalue=1)
    if w is None or h is None:
        return
    map_width, map_height = w, h
    map_data = [[-1 for _ in range(w)] for _ in range(h)]
    stage_scroll_x = 0.0
    stage_scroll_y = 0.0

# compact 2D list JSON write (as you requested earlier)
def save_map_2dlist(path=None):
    global map_data
    if path is None:
        path = save_file_dialog_json()
    if not path:
        return
    with open(path, 'w', encoding='utf-8') as f:
        f.write('[\n    ')
        f.write(',\n    '.join(json.dumps(row, separators=(',',':')) for row in map_data))
        f.write('\n]')
    print('Saved map (2D list) to', path)

def save_map_dict(path=None):
    global map_data, map_width, map_height
    if path is None:
        path = save_file_dialog_json()
    if not path:
        return
    payload = {'w': map_width, 'h': map_height, 'data': map_data}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    print('Saved map (dict) to', path)

def load_map(path=None):
    global map_data, map_width, map_height, stage_scroll_x, stage_scroll_y
    if path is None:
        path = open_file_dialog_json()
    if not path:
        return
    with open(path, 'r', encoding='utf-8') as f:
        obj = json.load(f)
    if isinstance(obj, dict) and 'data' in obj:
        map_data = obj['data']
        map_width = obj.get('w', len(map_data[0]) if map_data else 0)
        map_height = obj.get('h', len(map_data))
    elif isinstance(obj, list):
        map_data = obj
        map_height = len(map_data)
        map_width = len(map_data[0]) if map_height else 0
    else:
        print('Unsupported map format')
        return
    stage_scroll_x = 0.0
    stage_scroll_y = 0.0
    print('Loaded map', path)

# fill unpainted (Flood fill but only fill -1 areas)
def fill_unpainted(gx, gy):
    if not (0 <= gx < map_width and 0 <= gy < map_height):
        return
    # do nothing if no tile selected
    if selected_tile is None or selected_tile < 0:
        return
    target = map_data[gy][gx]
    if target != -1:
        return
    stack = [(gx, gy)]
    while stack:
        x, y = stack.pop()
        if map_data[y][x] == -1:
            map_data[y][x] = selected_tile
            for nx, ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if 0 <= nx < map_width and 0 <= ny < map_height and map_data[ny][nx] == -1:
                    stack.append((nx, ny))

# clamp helper
def clamp(v, a, b):
    return max(a, min(b, v))

# compute stage metrics and scrollbar presence with small iteration to account for mutual effect
def compute_stage_metrics(screen_w, screen_h):
    # tile pixel size on stage
    tile_px = TILE_SIZE * stage_zoom
    stage_w_px = map_width * tile_px
    stage_h_px = map_height * tile_px

    # initial available area (reserve some margin)
    avail_w = max(MIN_VIEW, screen_w - STAGE_OFFSET_X - 20)
    avail_h = max(MIN_VIEW, screen_h - STAGE_OFFSET_Y - 20)

    # iterate to account for scrollbar presence affecting available size
    for _ in range(3):
        need_hbar = stage_w_px > avail_w
        need_vbar = stage_h_px > avail_h
        new_avail_w = avail_w - (SCROLLBAR_SIZE if need_vbar else 0)
        new_avail_h = avail_h - (SCROLLBAR_SIZE if need_hbar else 0)
        # stop if stable
        if new_avail_w == avail_w and new_avail_h == avail_h:
            break
        avail_w, avail_h = new_avail_w, new_avail_h

    view_w = max(MIN_VIEW, avail_w)
    view_h = max(MIN_VIEW, avail_h)
    stage_rect = pygame.Rect(STAGE_OFFSET_X, STAGE_OFFSET_Y, view_w, view_h)

    return stage_rect, view_w, view_h, stage_w_px, stage_h_px

# compute scrollbar handle rects (absolute coordinates)
def compute_scroll_handles(stage_rect, view_w, view_h, stage_w_px, stage_h_px):
    h_rect = None
    v_rect = None
    tile_px = TILE_SIZE * stage_zoom

    # horizontal handle
    if stage_w_px > view_w:
        bar_w = max(20, int(view_w * view_w / stage_w_px))
        track_w = view_w - bar_w
        scrollable_x = stage_w_px - view_w
        if scrollable_x <= 0:
            norm_x = 0.0
        else:
            norm_x = clamp((-stage_scroll_x) / scrollable_x, 0.0, 1.0)
        bar_x = stage_rect.x + int(norm_x * track_w)
        h_rect = pygame.Rect(bar_x, stage_rect.y + view_h, bar_w, SCROLLBAR_SIZE)

    # vertical handle
    if stage_h_px > view_h:
        bar_h = max(20, int(view_h * view_h / stage_h_px))
        track_h = view_h - bar_h
        scrollable_y = stage_h_px - view_h
        if scrollable_y <= 0:
            norm_y = 0.0
        else:
            norm_y = clamp((-stage_scroll_y) / scrollable_y, 0.0, 1.0)
        bar_y = stage_rect.y + int(norm_y * track_h)
        v_rect = pygame.Rect(stage_rect.x + view_w, bar_y, SCROLLBAR_SIZE, bar_h)

    return h_rect, v_rect

# --- Copy / Paste helpers (new) ---
def copy_region(start, end):
    """Return 2D list (rows) for the rectangle from start to end inclusive."""
    x0, y0 = start
    x1, y1 = end
    x0, x1 = min(x0,x1), max(x0,x1)
    y0, y1 = min(y0,y1), max(y0,y1)
    buf = []
    for y in range(y0, y1+1):
        row = []
        for x in range(x0, x1+1):
            # bounds-safe: if out of map, store -1
            if 0 <= x < map_width and 0 <= y < map_height:
                row.append(map_data[y][x])
            else:
                row.append(-1)
        buf.append(row)
    return buf

def paste_buffer_at(top_left_x, top_left_y):
    """Paste copy_buffer (2D) into map_data at top-left (gx,gy)."""
    global copy_buffer
    if copy_buffer is None:
        return
    for y, row in enumerate(copy_buffer):
        for x, val in enumerate(row):
            gx = top_left_x + x
            gy = top_left_y + y
            if 0 <= gx < map_width and 0 <= gy < map_height:
                map_data[gy][gx] = val

# --- Drawing functions (palette, stage, help) ---
def draw_palette(surface):
    panel_rect = pygame.Rect(0, 0, PALETTE_PANEL_WIDTH, surface.get_height())
    pygame.draw.rect(surface, (40,40,40), panel_rect)
    title = font.render('Tileset Palette', True, (220,220,220))
    surface.blit(title, (PALETTE_PADDING, 8))

    if not tiles:
        hint = font.render('Press L to load tileset (PNG)', True, (180,180,180))
        surface.blit(hint, (PALETTE_PADDING, 36))
        return

    # clamp palette scroll so we don't scroll past content
    clamp_palette_scroll(surface.get_height())

    cols = PALETTE_COLS
    x0 = PALETTE_PADDING
    y0 = PALETTE_PADDING + palette_scroll

    for i, tile in enumerate(tiles):
        col = i % cols
        row = i // cols
        px = x0 + col * (PALETTE_TILE_SIZE + PALETTE_SPACING)
        py = y0 + row * (PALETTE_TILE_SIZE + PALETTE_SPACING)
        if py + PALETTE_TILE_SIZE < 0 or py > surface.get_height():
            continue
        scaled = pygame.transform.scale(tile, (PALETTE_TILE_SIZE, PALETTE_TILE_SIZE))
        surface.blit(scaled, (px, py))
        if i == selected_tile:
            pygame.draw.rect(surface, (255,200,0), (px-2, py-2, PALETTE_TILE_SIZE+4, PALETTE_TILE_SIZE+4), 2)


def clamp_palette_scroll(surface_h):
    """Clamp `palette_scroll` so palette content does not scroll beyond its bounds."""
    global palette_scroll
    if not tiles:
        palette_scroll = 0
        return
    cols = PALETTE_COLS
    rows = (len(tiles) + cols - 1) // cols
    content_h = PALETTE_PADDING + rows * (PALETTE_TILE_SIZE + PALETTE_SPACING)
    visible_h = surface_h
    min_scroll = min(0, visible_h - content_h)
    palette_scroll = clamp(palette_scroll, min_scroll, 0)

def draw_stage(surface):
    # compute metrics
    stage_rect, view_w, view_h, stage_w_px, stage_h_px = compute_stage_metrics(surface.get_width(), surface.get_height())

    # draw current stage name above the stage area
    label = f'Stage: {current_stage if current_stage else "(none)"}'
    title_s = font.render(label, True, (220,220,220))
    surface.blit(title_s, (stage_rect.x, stage_rect.y - 22))

    # clamp scroll to valid range
    min_x = min(0.0, view_w - stage_w_px)
    min_y = min(0.0, view_h - stage_h_px)
    global stage_scroll_x, stage_scroll_y
    stage_scroll_x = clamp(stage_scroll_x, min_x, 0.0)
    stage_scroll_y = clamp(stage_scroll_y, min_y, 0.0)

    # create stage surface sized to view (we draw only visible area)
    stage_surf = pygame.Surface((stage_rect.width, stage_rect.height))
    stage_surf.fill((30,30,30))

    tile_px = TILE_SIZE * stage_zoom

    # draw tiles into stage_surf coordinates (stage_scroll_x/ y are pixel offsets)
    for y in range(map_height):
        for x in range(map_width):
            tid = map_data[y][x]
            if 0 <= tid < len(tiles):
                t = tiles[tid]
                draw_x = int(x * tile_px + stage_scroll_x)
                draw_y = int(y * tile_px + stage_scroll_y)
                # cull quickly
                if draw_x + tile_px < 0 or draw_x > stage_rect.width or draw_y + tile_px < 0 or draw_y > stage_rect.height:
                    continue
                scaled = pygame.transform.scale(t, (int(tile_px), int(tile_px)))
                stage_surf.blit(scaled, (draw_x, draw_y))

    # grid lines
    for gx in range(map_width+1):
        sx = int(gx * tile_px + stage_scroll_x)
        if -1 <= sx <= stage_rect.width+1:
            pygame.draw.line(stage_surf, (80,80,80), (sx, 0), (sx, stage_rect.height))
    for gy in range(map_height+1):
        sy = int(gy * tile_px + stage_scroll_y)
        if -1 <= sy <= stage_rect.height+1:
            pygame.draw.line(stage_surf, (80,80,80), (0, sy), (stage_rect.width, sy))

    # border for logical stage size (inside stage_surf)
    pygame.draw.rect(stage_surf, (120,120,120), (0, 0, int(stage_w_px), int(stage_h_px)), 2)

    # if currently selecting copy region (right-drag), draw selection rectangle on stage_surf
    if copy_selecting and copy_start and copy_end:
        sx0, sy0 = copy_start
        sx1, sy1 = copy_end
        x0, x1 = min(sx0, sx1), max(sx0, sx1)
        y0, y1 = min(sy0, sy1), max(sy0, sy1)
        sel_x = int(x0 * tile_px + stage_scroll_x)
        sel_y = int(y0 * tile_px + stage_scroll_y)
        sel_w = int((x1 - x0 + 1) * tile_px)
        sel_h = int((y1 - y0 + 1) * tile_px)
        pygame.draw.rect(stage_surf, (0,200,255), (sel_x, sel_y, sel_w, sel_h), 2)

    # paste preview following mouse (if active)
    if paste_preview_active and copy_buffer is not None and paste_preview_pos is not None:
        px_gx, px_gy = paste_preview_pos
        for ry, row in enumerate(copy_buffer):
            for rx, val in enumerate(row):
                if val >= 0 and val < len(tiles):
                    t = tiles[val]
                    draw_x = int((px_gx + rx) * tile_px + stage_scroll_x)
                    draw_y = int((px_gy + ry) * tile_px + stage_scroll_y)
                    # only draw if within view
                    if draw_x + tile_px < 0 or draw_x > stage_rect.width or draw_y + tile_px < 0 or draw_y > stage_rect.height:
                        continue
                    surf = pygame.transform.scale(t, (int(tile_px), int(tile_px))).copy()
                    # make semi-transparent preview
                    surf.fill((255,255,255,160), special_flags=pygame.BLEND_RGBA_MULT)
                    stage_surf.blit(surf, (draw_x, draw_y))
        # draw outline around preview area
        w_px = int(len(copy_buffer[0]) * tile_px)
        h_px = int(len(copy_buffer) * tile_px)
        top_left_x = int(px_gx * tile_px + stage_scroll_x)
        top_left_y = int(px_gy * tile_px + stage_scroll_y)
        pygame.draw.rect(stage_surf, (0,255,0), (top_left_x, top_left_y, w_px, h_px), 2)

    # blit stage_surf to main screen at stage_rect position
    surface.blit(stage_surf, (stage_rect.x, stage_rect.y))

    # draw scrollbars on main surface
    h_rect, v_rect = compute_scroll_handles(stage_rect, view_w, view_h, stage_w_px, stage_h_px)
    # draw tracks and handles
    if h_rect:
        # track
        pygame.draw.rect(surface, (100,100,100), (stage_rect.x, stage_rect.y + view_h, view_w, SCROLLBAR_SIZE))
        pygame.draw.rect(surface, (200,200,200), h_rect)
    if v_rect:
        # track: avoid overlapping horizontal track area (if h_rect exists, its height sits below view_h)
        track_h = view_h - (SCROLLBAR_SIZE if h_rect else 0)
        pygame.draw.rect(surface, (100,100,100), (stage_rect.x + view_w, stage_rect.y, SCROLLBAR_SIZE, track_h))
        pygame.draw.rect(surface, (200,200,200), v_rect)

    return stage_rect, view_w, view_h, stage_w_px, stage_h_px, h_rect, v_rect

def draw_help(surface):
    lines = [
        '[L] Load tileset  [P] Load project  [S] Save project  [K] Save (alias)',
        '[M] Select stage  [R] Rename stage  [E] Resize stage',
        'Left: paint  Right: select/copy  Shift+Left: fill unpainted  Esc: cancel copy/preview',
        '[C] Copy selection  LeftClick while preview: paste  MouseWheel: smooth zoom (stage) / scroll (palette)'
    ]
    x = STAGE_OFFSET_X
    y = surface.get_height() - 24*len(lines) - 10
    for i, line in enumerate(lines):
        txt = font.render(line, True, (200,200,200))
        surface.blit(txt, (x, y + i*24))

# --- Initialization ---
new_map(map_width, map_height)   # fills map_data

# interaction drag state for scrollbars
dragging = None   # None / 'h' / 'v'
drag_offset = 0

# --- Main loop ---
running = True
while running:
    mx, my = pygame.mouse.get_pos()
    mods = pygame.key.get_mods()

    # compute metrics and handles every frame (for input & drawing)
    stage_rect, view_w, view_h, stage_w_px, stage_h_px = compute_stage_metrics(screen.get_width(), screen.get_height())
    h_handle, v_handle = compute_scroll_handles(stage_rect, view_w, view_h, stage_w_px, stage_h_px)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.VIDEORESIZE:
            screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            # immediately recompute stage metrics and clamp scroll so editor follows window resize
            stage_rect_tmp, view_w_tmp, view_h_tmp, stage_w_px_tmp, stage_h_px_tmp = compute_stage_metrics(screen.get_width(), screen.get_height())
            min_xt = min(0.0, view_w_tmp - stage_w_px_tmp)
            min_yt = min(0.0, view_h_tmp - stage_h_px_tmp)
            stage_scroll_x = clamp(stage_scroll_x, min_xt, 0.0)
            stage_scroll_y = clamp(stage_scroll_y, min_yt, 0.0)

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                # cancel copy/paste preview
                copy_selecting = False
                copy_start = None
                copy_end = None
                # cancel buffer & preview
                paste_preview_active = False
                paste_preview_pos = None
                copy_buffer = None
                # always clear tile selection on Esc
                selected_tile = -1
            elif event.key == pygame.K_l:
                load_tileset()
            elif event.key == pygame.K_p:
                # Load full project JSON (multiple stages)
                load_project_json()
            elif event.key == pygame.K_s:
                # Save project JSON (main save key)
                save_project_json()
            elif event.key == pygame.K_k:
                # alias save
                save_project_json()
            elif event.key == pygame.K_m:
                # Select stage from loaded project (dropdown)
                print('KEY M pressed: invoking select_stage_dialog()')
                select_stage_dialog()
            elif event.key == pygame.K_r:
                prompt_rename_stage()
            elif event.key == pygame.K_e:
                prompt_resize_stage()
            # optional: quick-copy key (C) to copy currently selecting region (if any)
            elif event.key == pygame.K_c:
                if copy_start and copy_end:
                    copy_buffer = copy_region(copy_start, copy_end)
                    paste_preview_active = True
                    paste_preview_pos = None
                    print("Copied region:", len(copy_buffer), "rows x", len(copy_buffer[0]) if copy_buffer else 0, "cols")

        elif event.type == pygame.MOUSEWHEEL:
            # palette scroll vs stage zoom
            if mx < PALETTE_PANEL_WIDTH:
                # invert palette wheel direction per user's request
                palette_scroll += event.y * (PALETTE_TILE_SIZE + PALETTE_SPACING)
                # clamp after change
                clamp_palette_scroll(screen.get_height())
            else:
                # smooth zooming: scale by a small factor per wheel step and keep mouse anchor
                old_zoom = stage_zoom
                factor = 1.12 ** event.y
                stage_zoom = max(0.5, min(16.0, stage_zoom * factor))
                # keep mouse world coordinate stable (if inside stage)
                if stage_rect.collidepoint(mx, my):
                    local_x = mx - stage_rect.x
                    local_y = my - stage_rect.y
                    tile_px_old = TILE_SIZE * old_zoom
                    tile_px_new = TILE_SIZE * stage_zoom
                    # world (tile) coords at mouse before zoom
                    world_x = (local_x - stage_scroll_x) / tile_px_old
                    world_y = (local_y - stage_scroll_y) / tile_px_old
                    # new scroll to keep same world_x under mouse
                    stage_scroll_x = local_x - world_x * tile_px_new
                    stage_scroll_y = local_y - world_y * tile_px_new
                # clamp scroll to new sizes
                stage_rect2, view_w2, view_h2, stage_w_px2, stage_h_px2 = compute_stage_metrics(screen.get_width(), screen.get_height())
                min_x = min(0.0, view_w2 - stage_w_px2)
                min_y = min(0.0, view_h2 - stage_h_px2)
                stage_scroll_x = clamp(stage_scroll_x, min_x, 0.0)
                stage_scroll_y = clamp(stage_scroll_y, min_y, 0.0)

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                left_down = True
                # If we have an active paste preview, left-click will paste at current preview pos (if inside stage)
                if paste_preview_active and copy_buffer is not None:
                    if stage_rect.collidepoint(mx, my) and paste_preview_pos is not None:
                        gx, gy = paste_preview_pos
                        paste_buffer_at(gx, gy)
                        # keep paste preview active (user may paste multiple times) OR disable after paste:
                        # here we disable after one paste:
                        paste_preview_active = False
                        paste_preview_pos = None
                else:
                    # palette click?
                    if mx < PALETTE_PANEL_WIDTH:
                        px = (mx - PALETTE_PADDING) // (PALETTE_TILE_SIZE + PALETTE_SPACING)
                        py = (my - PALETTE_PADDING - palette_scroll) // (PALETTE_TILE_SIZE + PALETTE_SPACING)
                        idx = int(py) * PALETTE_COLS + int(px)
                        if 0 <= idx < len(tiles):
                            selected_tile = idx
                    else:
                        # check scrollbar handles first
                        if h_handle and h_handle.collidepoint(mx, my):
                            dragging = 'h'
                            drag_offset = mx - h_handle.x
                        elif v_handle and v_handle.collidepoint(mx, my):
                            dragging = 'v'
                            drag_offset = my - v_handle.y
                        else:
                            # stage click -> paint or fill
                            if stage_rect.collidepoint(mx, my):
                                local_x = mx - stage_rect.x
                                local_y = my - stage_rect.y
                                tile_px = TILE_SIZE * stage_zoom
                                gx = int((local_x - stage_scroll_x) / tile_px)
                                gy = int((local_y - stage_scroll_y) / tile_px)
                                if 0 <= gx < map_width and 0 <= gy < map_height:
                                    if selected_tile is None or selected_tile < 0:
                                        # no tile selected -> cannot paint
                                        pass
                                    else:
                                        if mods & pygame.KMOD_SHIFT:
                                            fill_unpainted(gx, gy)
                                        else:
                                            map_data[gy][gx] = selected_tile

            elif event.button == 3:
                right_down = True
                # start selection for copy if inside stage
                if stage_rect.collidepoint(mx, my):
                    local_x = mx - stage_rect.x
                    local_y = my - stage_rect.y
                    tile_px = TILE_SIZE * stage_zoom
                    gx = int((local_x - stage_scroll_x) / tile_px)
                    gy = int((local_y - stage_scroll_y) / tile_px)
                    # clamp to stage bounds
                    gx = clamp(gx, 0, map_width-1)
                    gy = clamp(gy, 0, map_height-1)
                    copy_selecting = True
                    copy_start = (int(gx), int(gy))
                    copy_end = (int(gx), int(gy))
                    # while selecting, preview is disabled
                    paste_preview_active = False
                    paste_preview_pos = None

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                left_down = False
                dragging = None
            elif event.button == 3:
                right_down = False
                # finish selection -> copy buffer and enable paste preview
                if copy_selecting and copy_start and copy_end:
                    copy_buffer = copy_region(copy_start, copy_end)
                    paste_preview_active = True
                    # set initial preview position to where mouse currently is (if inside stage)
                    if stage_rect.collidepoint(mx, my):
                        local_x = mx - stage_rect.x
                        local_y = my - stage_rect.y
                        tile_px = TILE_SIZE * stage_zoom
                        gx = int((local_x - stage_scroll_x) / tile_px)
                        gy = int((local_y - stage_scroll_y) / tile_px)
                        paste_preview_pos = (int(clamp(gx, 0, map_width-1)), int(clamp(gy, 0, map_height-1)))
                    else:
                        paste_preview_pos = None
                copy_selecting = False

        elif event.type == pygame.MOUSEMOTION:
            # dragging scrollbar handles
            if dragging == 'h' and h_handle:
                # compute track width
                bar_w = h_handle.width
                track_w = view_w - bar_w
                if track_w <= 0:
                    norm = 0.0
                else:
                    new_bar_x = clamp(mx - drag_offset, stage_rect.x, stage_rect.x + track_w)
                    norm = (new_bar_x - stage_rect.x) / track_w
                # map normalized to stage_scroll_x (negative)
                scrollable_x = stage_w_px - view_w
                if scrollable_x <= 0:
                    stage_scroll_x = 0.0
                else:
                    stage_scroll_x = - norm * scrollable_x
            elif dragging == 'v' and v_handle:
                bar_h = v_handle.height
                track_h = view_h - bar_h
                if track_h <= 0:
                    norm = 0.0
                else:
                    new_bar_y = clamp(my - drag_offset, stage_rect.y, stage_rect.y + track_h)
                    norm = (new_bar_y - stage_rect.y) / track_h
                scrollable_y = stage_h_px - view_h
                if scrollable_y <= 0:
                    stage_scroll_y = 0.0
                else:
                    stage_scroll_y = - norm * scrollable_y
            else:
                # painting while dragging left or erasing with right
                if left_down and not dragging and mx >= STAGE_OFFSET_X:
                    if stage_rect.collidepoint(mx, my):
                        local_x = mx - stage_rect.x
                        local_y = my - stage_rect.y
                        tile_px = TILE_SIZE * stage_zoom
                        gx = int((local_x - stage_scroll_x) / tile_px)
                        gy = int((local_y - stage_scroll_y) / tile_px)
                        if 0 <= gx < map_width and 0 <= gy < map_height:
                                if selected_tile is None or selected_tile < 0:
                                    pass
                                else:
                                    map_data[gy][gx] = selected_tile
                if right_down and copy_selecting and stage_rect.collidepoint(mx, my):
                    # update selection end while right-button dragging
                    local_x = mx - stage_rect.x
                    local_y = my - stage_rect.y
                    tile_px = TILE_SIZE * stage_zoom
                    gx = int((local_x - stage_scroll_x) / tile_px)
                    gy = int((local_y - stage_scroll_y) / tile_px)
                    gx = int(clamp(gx, 0, map_width-1))
                    gy = int(clamp(gy, 0, map_height-1))
                    copy_end = (gx, gy)
                # update paste preview follow mouse (when active)
                if paste_preview_active and copy_buffer is not None:
                    if stage_rect.collidepoint(mx, my):
                        local_x = mx - stage_rect.x
                        local_y = my - stage_rect.y
                        tile_px = TILE_SIZE * stage_zoom
                        gx = int((local_x - stage_scroll_x) / tile_px)
                        gy = int((local_y - stage_scroll_y) / tile_px)
                        # clamp so top-left stays within stage (we allow partial off-screen pasting but clamp to stage coords)
                        gx = int(clamp(gx, 0, map_width-1))
                        gy = int(clamp(gy, 0, map_height-1))
                        paste_preview_pos = (gx, gy)
                    else:
                        paste_preview_pos = None

    # ensure scroll is clamped each frame
    stage_rect, view_w, view_h, stage_w_px, stage_h_px = compute_stage_metrics(screen.get_width(), screen.get_height())
    min_x = min(0.0, view_w - stage_w_px)
    min_y = min(0.0, view_h - stage_h_px)
    stage_scroll_x = clamp(stage_scroll_x, min_x, 0.0)
    stage_scroll_y = clamp(stage_scroll_y, min_y, 0.0)

    # --- Drawing ---
    screen.fill((30,30,30))
    draw_palette(screen)
    draw_stage(screen)
    draw_help(screen)

    pygame.display.flip()
    clock.tick(60)

try:
    root.destroy()
except Exception:
    pass
pygame.quit()
sys.exit()
