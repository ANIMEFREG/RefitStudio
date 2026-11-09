# Refit Studio - мастерская в Blender: подгонка одежды Cyberpunk 2077 под выбранное тело.
# Запускает лаунчер: blender --python studio.py -- --profile <id профиля тела>
# Одежда загружается в координатах игры: где она стоит относительно тела здесь, там будет и в игре.
# Менять можно только положение точек, не их количество.
import bpy, os, sys, re, json, shutil, zipfile, traceback, datetime
import numpy as np
from bpy.app.handlers import persistent

CORE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CORE)
import common as C
import fit
from meshpos import MeshPos, has_geometry

tr = C.tr
CLOTH = tr('Одежда', 'Clothing')
CLOTH_NAMES = ('Одежда', 'Clothing')  # сохранённые работы могли быть сделаны на другом языке
TAB = tr('Рефит', 'Refit')
TATTOO_OBJ = tr('Татуировка', 'Tattoo')
SKIN = (0.85, 0.66, 0.55, 1)
CLOTH_COLOR = (0.35, 0.45, 0.9, 1)
TATTOO_COLOR = (0.1, 0.8, 0.8, 1)

state = {'mods': [], 'meshes': [], 'mod': None, 'mesh': None, 'raw': None, 'json': None,
         'orig': None, 'ranges': None, 'base': None, 'tris': None, 'saves': []}
B = {'body': None}  # загруженный профиль тела


def arg(name):
    a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else None


def body():
    if B['body'] is None:
        pid = arg('--profile') or C.load_config().get('profile')
        if not pid or not os.path.isdir(C.profile_dir(pid)):
            raise RuntimeError(tr('Не выбрано тело. Закрой Blender и выбери тело в лаунчере.',
                                  'No body selected. Close Blender and choose a body in the launcher.'))
        B['body'] = fit.Body(C.profile_dir(pid))
    return B['body']


def body_label():
    try:
        return C.clean_mod_name(body().info['name'])
    except Exception:
        return '?'


def report(op, msg, level='INFO'):
    bpy.context.scene.refit_status = msg
    op.report({level}, msg)


class Progress:
    """Проценты у курсора и текст в строке состояния, чтобы было видно, что Blender работает."""

    def __init__(self, title):
        self.title = title
        self.wm = bpy.context.window_manager
        self.wm.progress_begin(0, 100)

    def __call__(self, pct, text=''):
        self.wm.progress_update(int(pct))
        try:
            bpy.context.workspace.status_text_set(f'{self.title}: {text} ({int(pct)}%)')
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        except Exception:
            pass

    def done(self):
        self.wm.progress_end()
        try:
            bpy.context.workspace.status_text_set(None)
        except Exception:
            pass


# ---------- сцена ----------

def set_color_attr(ob, colors):
    me = ob.data
    attr = me.color_attributes.get('fit') or me.color_attributes.new('fit', 'FLOAT_COLOR', 'POINT')
    attr.data.foreach_set('color', np.asarray(colors, np.float32).ravel())
    me.color_attributes.active_color = attr
    me.update()


def build_object(name, pos, tris, coll, color):
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(pos))
    me.vertices.foreach_set('co', np.asarray(pos, np.float32).ravel())
    tris = np.asarray(tris, np.int64)
    tris = tris[(tris < len(pos)).all(1)]
    me.loops.add(len(tris) * 3)
    me.polygons.add(len(tris))
    me.loops.foreach_set('vertex_index', tris.astype(np.int32).ravel())
    me.polygons.foreach_set('loop_start', np.arange(0, len(tris) * 3, 3, dtype=np.int32))
    me.polygons.foreach_set('use_smooth', np.ones(len(tris), bool))
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    set_color_attr(ob, np.tile(color, (len(pos), 1)))
    return ob


def setup_view():
    """Вид спереди на персонажа (он смотрит вдоль +Y), цвет по точкам, наша вкладка справа.
    Окна перебираем явно: из таймера у Blender нет «текущего» экрана."""
    from mathutils import Euler
    from math import radians
    screens = [w.screen for w in bpy.context.window_manager.windows if w.screen]
    for area in (a for s in screens for a in s.areas):
        if area.type == 'VIEW_3D':
            sp = area.spaces.active
            sp.shading.type = 'SOLID'
            sp.shading.color_type = 'VERTEX'
            r3 = sp.region_3d
            r3.view_perspective = 'PERSP'
            r3.view_rotation = Euler((radians(82), 0, radians(160))).to_quaternion()
            r3.view_location = (0, 0, 1.0)
            r3.view_distance = 3.0
            sp.show_region_ui = True
            if not bpy.app.background:
                tidy_view(sp)  # без панели инструментов Blender, сетки, осей и служебного текста
            for region in area.regions:
                if region.type == 'UI':
                    try:
                        region.active_panel_category = TAB  # сразу наша вкладка справа
                    except Exception:
                        pass


BODY_COLL = tr('Тело', 'Body')
PART_LABELS = {'torso': tr('Тело', 'Body'), 'arm_l': tr('Рука L', 'Arm L'), 'arm_r': tr('Рука R', 'Arm R'),
               'feet': tr('Ступни', 'Feet')}


def setup_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    coll = bpy.data.collections.new(BODY_COLL)
    bpy.context.scene.collection.children.link(coll)
    b = body()
    for part, pos, tris in b.display:
        if part == 'feet':
            continue  # ступни дублируют низ тела (это вариант под обувь), в сцене не нужны
        build_object(PART_LABELS.get(part, part), pos, tris, coll, SKIN).hide_select = True
    bpy.context.scene.refit_body = body_label()
    show_tattoo(bpy.context.scene.refit_tattoo)
    setup_view()


def tattoo_items(self, context):
    items = [('none', tr('Без татуировки', 'No tattoo'), tr('Татуировка не учитывается', 'Tattoo is ignored'))]
    try:
        for key, has_body in body().tattoos():
            ok = has_body or tattoo_refit(key) is not None
            items.append((key, tr('Татуировка ', 'Tattoo ') + key[-2:] +
                          ('' if ok else tr(' (без рефита под тело)', ' (not refitted for this body)')),
                          tr('Есть рефит под это тело: одежда подгоняется полностью',
                             'Refitted for this body: clothing is fitted fully') if ok
                          else tr('Рефита под тело нет: одежда не уйдёт под её оболочку (но и грудь там не сузится)',
                                  'Not refitted for this body: clothing stays above its shell '
                                  '(but will not get slimmer there either)')))
    except Exception:
        C.log('tattoo list:\n' + traceback.format_exc())
    return C_keep('tattoos', items)


_enum_keep = {}


def C_keep(key, items):
    # Blender не копирует строки из динамических списков меню: держим список у себя,
    # иначе Python освободит строки и в меню будет "мусор".
    _enum_keep[key] = items
    return items


def tattoo_refit(key):
    """Позиции татуировки после нашего рефита (кнопка «Рефит татуировок»), если он был."""
    if 'tattoo_refit' not in B:
        p = os.path.join(body().folder, 'tattoo_refit.npz')
        B['tattoo_refit'] = dict(np.load(p)) if os.path.isfile(p) else {}
    return B['tattoo_refit'].get(key)


def tattoo_shape(key):
    """(позиции, нормали, треугольники) татуировки на этом теле и нужен ли режим оболочки."""
    b = body()
    pos, n, tris = b.tattoo_mesh(key)
    has_body = dict(b.tattoos()).get(key)
    if not has_body:
        r = tattoo_refit(key)
        if r is not None:
            return r, fit.vertex_normals(r, tris), tris, False
    return pos, n, tris, not has_body


def show_tattoo(key):
    old = bpy.data.objects.get(TATTOO_OBJ)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    if not key or key == 'none':
        return
    pos, _, tris, _ = tattoo_shape(key)
    coll = bpy.data.collections.get(BODY_COLL) or bpy.context.scene.collection
    ob = build_object(TATTOO_OBJ, pos, tris, coll, TATTOO_COLOR)
    ob.hide_select = True
    ob.display_type = 'WIRE'


def on_tattoo(self, context):
    try:
        show_tattoo(self.refit_tattoo)
    except Exception as e:
        C.log('tattoo: ' + str(e))


def shell_key(context):
    """Татуировка, под оболочку которой нельзя уводить ткань (нет рефита под тело)."""
    key = context.scene.refit_tattoo
    if key and key != 'none':
        return key if tattoo_shape(key)[3] else None
    return None


def tattoo_obstacles(context):
    """Оболочка выбранной татуировки как препятствие для ткани: [(на этом теле, на обычном теле)].
    Под неё ткань не уводим, иначе в игре рисунок проступит сквозь одежду."""
    key = context.scene.refit_tattoo
    if not key or key == 'none' or fit.BVHTree is None:
        return []
    cache = B.setdefault('obstacles', {})
    if key not in cache:
        b = body()
        tp, _, tt, _ = tattoo_shape(key)
        vp, vt = b.z[key + '_van'], b.z[key + '_van_tris']
        cache[key] = fit.tattoo_obstacles(b, tp, tt, vp, vt)
    return cache[key]


# ---------- выбор мода и вещи ----------

def scan_mods():
    state['mods'] = C.scan_mods()
    return state['mods']


import threading
_flags = {'data': None, 'thread': None}


def start_clothing_scan():
    """В фоне узнаём, в каких модах есть одежда (WolvenKit, ~2 с на новый мод; дальше из кэша)."""
    def work():
        try:
            _flags['data'] = C.clothing_flags(C.scan_mods())
        except Exception:
            C.log('clothing scan:\n' + traceback.format_exc())
            _flags['data'] = {}
    _flags['thread'] = threading.Thread(target=work, daemon=True)
    _flags['thread'].start()


def clothing_flags_ready(prog=None):
    """Дождаться фоновой проверки и досчитать моды, появившиеся после неё."""
    t = _flags['thread']
    if t is None:
        start_clothing_scan()
        t = _flags['thread']
    while t.is_alive():
        if prog:
            prog(50, tr('ищу моды с одеждой (первый раз - до минуты)', 'finding clothing mods (first time - up to a minute)'))
        t.join(0.3)
    fl = _flags['data'] or {}
    if any(m['path'].lower() not in fl for m in state['mods']):
        fl = _flags['data'] = C.clothing_flags(state['mods'],
                                               (lambda d, n: prog(100 * d / n, f'{d}/{n}')) if prog else None)
    return fl


def mod_items(self, context):
    mods = state['mods'] or scan_mods()
    fl = _flags['data'] or {}
    show_all = context is None or getattr(context.scene, 'refit_all_mods', True) or not fl
    idx = [i for i, m in enumerate(mods) if show_all or m.get('manual') or fl.get(m['path'].lower(), True)]
    names = {i: C.clean_mod_name(mods[i]['name']) for i in idx}
    counts = {}
    for n in names.values():
        counts[n] = counts.get(n, 0) + 1
    # одинаковые после чистки названия различаем по исходному имени папки
    return C_keep('mods', [(str(i), names[i] if counts[names[i]] == 1 else
                            f'{names[i]} ({mods[i]["name"][len(names[i]):].strip(" -_")[:20]})',
                            mods[i]['path']) for i in idx])


def looks_female(p):
    p = p.lower().replace('\\', '/')
    name = p.rsplit('/', 1)[-1]
    return (name.startswith('w_') or '_w_' in name or 'pwa' in p or name.startswith('wa_')
            or '_wa_' in name or 'female' in p or '/w/' in p or 'fem' in name)


def looks_male(p):
    p = p.lower().replace('\\', '/')
    name = p.rsplit('/', 1)[-1]
    return (name.startswith('m_') or '_m_' in name or 'pma' in p or name.startswith('ma_')
            or '_ma_' in name or '/male' in p or '/m/' in p) and not looks_female(p)


# Версии одежды под другие тела: авто-подгонка считает, что вещь сделана под обычное тело,
# поэтому брать надо версию под обычное тело (base_body / vanilla).
OTHER_BODIES = ('angel', 'ebb', 'ebbp', 'ebbrb', 'ebbprb', 'vtk', 'evb', 'eve', 'vhd', 'rb', 'gymfiend',
                'lush', 'solo', 'bigboobs', 'flat', 'small', 'big', 'songbird', 'spawn0', 'elegy',
                'freyja', 'hyst_ebb', 'hyst_rb', 'atlas', 'adonis', 'valentine')
BODY_NAMES = {'angel': 'Angel', 'ebb': 'EBB', 'ebbp': 'EBB+', 'ebbrb': 'EBB RB', 'ebbprb': 'EBB+ RB',
              'vtk': 'VTK', 'evb': 'EVB', 'eve': 'EVE', 'vhd': 'VHD', 'rb': 'RB', 'gymfiend': 'Gymfiend',
              'lush': 'Lush', 'solo': 'Solo', 'bigboobs': tr('большая грудь', 'big breasts'),
              'flat': tr('плоская', 'flat'), 'small': tr('маленькая', 'small'), 'big': tr('большая', 'big'), 'songbird': 'Songbird', 'spawn0': 'Spawn0',
              'elegy': 'Elegy', 'freyja': 'Freyja'}
NOISE = {'w', 'm', 'wa', 'ma', 'pwa', 'pma', 'base', 'body', 'vanilla', 'mesh', 'meshes', 'xl', 'main',
         'female', 'male', 'fem', 'fpp', 'tpp', 'lod', 'lod0', 'lod1', 'items', 'item', 'clothing', 'clothes',
         'characters', 'common', 'player', 'archive', 'mod', 'mods', 'garment', 't0', 't1', 't2', 'a0', 's0',
         'l0', 'h0', 'g0', 'b0'}


def body_kind(path):
    name = os.path.splitext(os.path.basename(path))[0].lower()
    tokens = set(re.split(r'[_\-.]+', name))
    if 'base' in tokens or 'vanilla' in tokens or 'base_body' in name:
        return 'base'
    tag = (body().info.get('tag') or '').lower()
    if tag and tag in name:
        return 'this'
    if tokens & set(OTHER_BODIES):
        return 'other'
    return ''


def friendly(rel):
    """'base\\peachu\\gothic_skirt\\xl_meshes\\peachu_gothic_skirt_w_base_body.mesh' -> 'Gothic skirt — обычное тело'."""
    parts = rel.replace('/', '\\').lower().split('\\')
    name = os.path.splitext(parts[-1])[0]
    tokens = [t for t in re.split(r'[_\-.]+', name) if t]
    bodies = [BODY_NAMES[t] for t in tokens if t in BODY_NAMES]
    words = [t for t in tokens if t not in NOISE and t not in BODY_NAMES and not re.fullmatch(r'\d{3,}', t)]
    folders = [f for f in parts[:-1] if f not in NOISE and not f.endswith('meshes')]
    if words and len(words) > 1 and any(words[0] == f.split('_')[0] for f in folders[:2]):
        words = words[1:]
    if not words and folders:
        words = re.split(r'[_\-.]+', folders[-1])
    title = ' '.join(words).strip().capitalize() or name
    kind = body_kind(rel)
    if kind == 'base':
        title += tr(' — обычное тело', ' — vanilla body')
    elif kind == 'this':
        title += tr(' — уже под это тело', ' — already for this body')
    elif bodies:
        title += ' — ' + ', '.join(dict.fromkeys(bodies))
    return title


def mesh_items(self, context):
    items = []
    for i, m in enumerate(state['meshes']):
        kind = body_kind(m)
        mark = {'base': '★ ', 'other': '✗ ', 'this': '✓ '}.get(kind, '')
        items.append((str(i), mark + friendly(m), m))  # полный путь - во всплывающей подсказке
    return C_keep('meshes', items)


def mod_work(mod):
    return os.path.join(C.WORK, C.short_id(mod['path']))


def open_mod(mod, prog=None):
    """Распаковывает модели мода и составляет список вещей."""
    w = mod_work(mod)
    raw = os.path.join(w, 'raw')
    for d in (raw, raw + '_json'):
        C.rmtree(d)
    os.makedirs(raw)
    for n, a in enumerate(mod['archives']):
        if prog:
            prog(10 + 60 * n / len(mod['archives']), tr('распаковка ', 'unpacking ') + os.path.basename(a))
        C.wk('unbundle', a, '-o', raw, '-r', r'\.(mesh|ent|app)$')
    # .ent/.app хранят пути сжатыми: переводим в JSON, чтобы найти шаблоны вида {gender}_{body}.mesh
    if prog:
        prog(75, tr('чтение .ent/.app', 'reading .ent/.app'))
    try:
        os.makedirs(raw + '_json', exist_ok=True)
        for pat in ('*.ent', '*.app'):
            C.wk('convert', 'serialize', raw, '-o', raw + '_json', '-w', pat)
    except Exception:
        pass
    meshes = []
    for dp, _, fs in os.walk(raw):
        for f in fs:
            full = os.path.join(dp, f)
            # Файлы-хранилища материалов (обычно в ...\materials\..., пара КБ) - без 3D-модели
            if f.lower().endswith('.mesh') and os.path.getsize(full) > 16384 \
                    and '\\materials\\' not in full.lower():
                rel = os.path.relpath(full, raw)
                if not looks_male(rel):
                    meshes.append(rel)
    meshes.sort(key=lambda m: (not looks_female(m), body_kind(m) != 'base', body_kind(m) == 'other', m.lower()))
    state.update(mod=mod, raw=raw, meshes=meshes)
    json.dump({'mod': mod}, open(os.path.join(w, 'mod.json'), 'w', encoding='utf-8'), ensure_ascii=False)


class REFIT_OT_add_mod(bpy.types.Operator):
    bl_idname = 'refit.add_mod'
    bl_label = tr('Добавить мод одежды', 'Add clothing mod')
    bl_description = tr('Выбрать папку мода (или его .archive) вручную. Он будет помечен как одежда '
                        'и всегда будет в списке',
                        'Pick a mod folder (or its .archive) manually. It is marked as clothing '
                        'and always shown in the list')
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    filter_glob: bpy.props.StringProperty(default='*.archive', options={'HIDDEN'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        p = self.filepath if self.filepath.lower().endswith('.archive') and os.path.isfile(self.filepath) \
            else self.directory
        p = os.path.normpath(p.rstrip('\\/')) if p else ''
        if not p or not C.manual_mod(p):
            raise UserError(tr('В этой папке нет файлов .archive. Выбери папку мода или сам .archive.',
                               'No .archive files in this folder. Pick the mod folder or the .archive itself.'))
        C.set_manual_mod(p, True)
        scan_mods()
        m = next((m for m in state['mods'] if m.get('manual_path') == p), None)
        report(self, tr('Добавлено в список одежды: ', 'Added to the clothing list: ') +
               C.clean_mod_name(m['name'] if m else os.path.basename(p)))
        return {'FINISHED'}


def manual_items(self, context):
    mods = state['mods'] or scan_mods()
    return C_keep('manual', [(m['manual_path'], C.clean_mod_name(m['name']), m['manual_path'])
                             for m in mods if m.get('manual')] or
                  [('-', tr('(нет добавленных вручную)', '(none added manually)'), '')])


class REFIT_OT_remove_mod(bpy.types.Operator):
    bl_idname = 'refit.remove_mod'
    bl_label = tr('Убрать из списка', 'Remove from list')
    bl_description = tr('Убрать мод, добавленный вручную, из списка одежды. Файлы мода не удаляются',
                        'Remove a manually added mod from the clothing list. The mod files are not deleted')
    bl_property = 'mod'
    mod: bpy.props.EnumProperty(items=manual_items)

    def invoke(self, context, event):
        scan_mods()
        if not any(m.get('manual') for m in state['mods']):
            report(self, tr('Нет модов, добавленных вручную.', 'No manually added mods.'), 'WARNING')
            return {'CANCELLED'}
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.mod in ('', '-'):
            return {'CANCELLED'}
        name = next((C.clean_mod_name(m['name']) for m in state['mods'] if m.get('manual_path') == self.mod),
                    os.path.basename(self.mod))
        C.set_manual_mod(self.mod, False)
        scan_mods()
        report(self, tr('Убрано из списка (файлы не тронуты): ', 'Removed from the list (files untouched): ') + name)
        return {'FINISHED'}


class REFIT_OT_choose_mod(bpy.types.Operator):
    bl_idname = 'refit.choose_mod'
    bl_label = tr('Выбрать мод одежды', 'Choose clothing mod')
    bl_description = tr('Поиск по модам из папок, указанных в лаунчере (Vortex, MO2, папка игры)',
                        'Search the mods in the folders set in the launcher (Vortex, MO2, game folder)')
    bl_property = 'mod'
    mod: bpy.props.EnumProperty(items=mod_items)

    def invoke(self, context, event):
        scan_mods()
        if not state['mods']:
            report(self, tr('Модов не найдено. Проверь папки с модами в лаунчере.',
                            'No mods found. Check the mod folders in the launcher.'), 'WARNING')
            return {'CANCELLED'}
        if not context.scene.refit_all_mods:
            prog = Progress(tr('Моды', 'Mods'))
            try:
                fl = clothing_flags_ready(prog)
            finally:
                prog.done()
            if fl and not any(m.get('manual') or fl.get(m['path'].lower(), True) for m in state['mods']):
                report(self, tr('Не нашёл модов с одеждой. Включи «Показать все моды».',
                                'No clothing mods found. Turn on "Show all mods".'), 'WARNING')
                return {'CANCELLED'}
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        mod = state['mods'][int(self.mod)]
        prog = Progress(tr('Открываю мод', 'Opening mod'))
        try:
            open_mod(mod, prog)
        finally:
            prog.done()
        context.scene.refit_mod = mod['name']
        context.scene.refit_mesh = ''
        report(self, tr(f'Мод: {C.clean_mod_name(mod["name"])}. Вещей: {len(state["meshes"])}. '
                        '★ - под обычное тело (бери их), ✗ - под другие тела, ✓ - уже под твоё тело.',
                        f'Mod: {C.clean_mod_name(mod["name"])}. Items: {len(state["meshes"])}. '
                        '★ - for the vanilla body (use these), ✗ - for other bodies, ✓ - already for your body.'))
        return {'FINISHED'}


def load_item(context, rel, json_path, orig=None):
    """Создаёт объект одежды из JSON меша. orig - исходные позиции (если вещь из сохранения)."""
    pos, tris, ranges = MeshPos(json_path).lod0()
    old = cloth_obj()
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    ob = build_object(CLOTH, pos, tris, context.scene.collection, CLOTH_COLOR)
    state.update(mesh=rel, json=json_path, orig=(orig if orig is not None else pos.copy()), ranges=ranges, base=None,
                 tris=tris)
    context.scene.refit_mesh = rel
    try:
        context.scene.refit_mesh_name = default_mesh_name()  # имя для «Сохранить .mesh» во вкладке «Экспорт»
    except Exception:
        pass
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    context.view_layer.objects.active = ob
    return ob, pos


class REFIT_OT_choose_mesh(bpy.types.Operator):
    bl_idname = 'refit.choose_mesh'
    bl_label = tr('Выбрать вещь', 'Choose item')
    bl_property = 'mesh'
    mesh: bpy.props.EnumProperty(items=mesh_items)

    def invoke(self, context, event):
        if not state['meshes']:
            report(self, tr('Сначала выбери мод одежды', 'Choose a clothing mod first'), 'WARNING')
            return {'CANCELLED'}
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rel = state['meshes'][int(self.mesh)]
        edit = os.path.join(mod_work(state['mod']), 'edit')
        C.rmtree(edit)
        os.makedirs(edit)
        dst = os.path.join(edit, 'item.mesh')
        shutil.copyfile(C.lp(os.path.join(state['raw'], rel)), dst)
        jpath = C.serialize(dst, edit)
        if not has_geometry(jpath):
            report(self, os.path.basename(rel) + tr(' - это файл материалов без 3D-модели. Выбери другую вещь.',
                                                    ' is a materials file without a 3D model. Choose another item.'),
                   'WARNING')
            return {'CANCELLED'}
        ob, pos = load_item(context, rel, jpath)
        kind = body_kind(rel)
        if kind == 'other':
            report(self, tr(f'Внимание: {os.path.basename(rel)} - версия под другое тело. Авто-подгонка рассчитана '
                            'на версию под обычное тело (★), выбери лучше её.',
                            f'Note: {os.path.basename(rel)} is made for another body. Auto fit expects '
                            'the vanilla body version (★) - better pick that one.'), 'WARNING')
        elif kind == 'this':
            report(self, tr(f'{os.path.basename(rel)} уже сделана автором под твоё тело - авто-подгонка не нужна, '
                            'можно только поправить руками.',
                            f'{os.path.basename(rel)} is already made by the author for your body - no auto fit '
                            'needed, you can only touch it up by hand.'), 'WARNING')
        else:
            report(self, tr(f'Загружено: {os.path.basename(rel)} ({len(pos)} точек). Можно «Авто-подгонку» или сразу лепить.',
                            f'Loaded: {os.path.basename(rel)} ({len(pos)} points). Press "Auto fit" or start sculpting.'))
        return {'FINISHED'}


# ---------- правка ----------

def cloth_obj():
    for name in (CLOTH,) + CLOTH_NAMES:
        ob = bpy.data.objects.get(name)
        if ob:
            return ob
    return None


def get_pos(ob):
    """Позиции точек в мире: если вещь двигали целиком (G/R/S в режиме объекта), это тоже учитывается."""
    if ob.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    a = np.empty(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get('co', a)
    p = a.reshape(-1, 3)
    mw = np.array(ob.matrix_world)
    return p @ mw[:3, :3].T + mw[:3, 3]


def set_pos(ob, pos):
    """Записывает позиции в мире и сбрасывает перемещение объекта, чтобы оно не применилось дважды."""
    if ob.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    ob.matrix_world.identity()
    ob.data.vertices.foreach_set('co', np.asarray(pos, np.float64).ravel())
    ob.data.update()


def fit_points(points, context, tris=None):
    """Авто-подгонка с учётом выбранной татуировки. tris - треугольники вещи (сглаживание и натяжение)."""
    shell = shell_key(context)
    r = fit.autofit(points, body(), shell, tris)
    if not shell:
        r = fit.conform(r, points, body())
    return fit.settle(r, points, body(), tris, shells=tattoo_obstacles(context))


class REFIT_OT_autofit(bpy.types.Operator):
    bl_idname = 'refit.autofit'
    bl_label = tr('Авто-подгонка', 'Auto fit')
    bl_description = tr('Автоматическая подгонка под выбранное тело (туловище, ноги, руки; свободные части - плавно)',
                        'Automatic fit to the chosen body (torso, legs, arms; loose parts follow smoothly)')

    def execute(self, context):
        ob = cloth_obj()
        if not ob or state['orig'] is None:
            report(self, tr('Сначала загрузи вещь', 'Load an item first'), 'WARNING')
            return {'CANCELLED'}
        cur = get_pos(ob)
        base = state.get('base')
        if base is None or len(base) != len(cur):
            base = state['orig']
        # Ручные правки = чем текущая форма отличается от последней основы (оригинал или прошлая подгонка).
        # Подгоняем оригинал заново и накладываем правки сверху - так они не теряются.
        # С привязкой к телу правки отбрасываются: вещь садится туда, где её задумал автор.
        edits = np.zeros_like(cur) if context.scene.refit_anchor else cur - base
        prog = Progress(tr('Авто-подгонка', 'Auto fit'))
        try:
            prog(10, tr('считаю', 'computing'))
            shell = shell_key(context)
            tris = state.get('tris')
            fitted = fit.autofit(state['orig'], body(), shell, tris)
            result = fitted + edits
            if not shell:
                prog(40, tr('прилегание', 'fitting to skin'))
                # Ткань у тела ложится на новое тело там, где вещь стоит сейчас (с зазором как у автора)
                result = fit.conform(result, state['orig'], body())
            prog(60, tr('натяжение ткани', 'settling the cloth'))
            # Ткань держит форму автора (с ручными правками) и не уходит под кожу и под татуировку
            result = fit.settle(result, state['orig'] + edits, body(), tris, shells=tattoo_obstacles(context))
        finally:
            prog.done()
        set_pos(ob, result)
        state['base'] = result - edits
        set_color_attr(ob, np.tile(CLOTH_COLOR, (len(state['orig']), 1)))
        moved = float(np.abs(edits).max()) if len(edits) else 0
        report(self, tr('Авто-подгонка готова', 'Auto fit done') +
               (tr(' (привязка к телу: вещь на своём месте)', ' (snap to body: item is back in place)')
                if context.scene.refit_anchor else
                tr(', твои правки сохранены', ', your edits are kept') if moved > 1e-5 else '') +
               tr('. «Проверить посадку» покажет, где доработать.', '. "Check fit" shows what to touch up.'))
        return {'FINISHED'}


class REFIT_OT_reset(bpy.types.Operator):
    bl_idname = 'refit.reset'
    bl_label = tr('Вернуть оригинал', 'Reset to original')

    def execute(self, context):
        ob = cloth_obj()
        if ob and state['orig'] is not None:
            set_pos(ob, state['orig'])
            state['base'] = None
            set_color_attr(ob, np.tile(CLOTH_COLOR, (len(state['orig']), 1)))
            report(self, tr('Вещь возвращена к оригиналу автора.', "Item reset to the author's original."))
        return {'FINISHED'}


# ---------- предупреждения перед лепкой (окно посреди экрана, «больше не показывать») ----------

TIPS = {
    'sculpt': (tr('Лепка - осторожно', 'Sculpting - be careful'), tr(
        'Лепка двигает точки ткани вручную. Это сильный, но очень нежный инструмент.\n'
        'Одно неловкое движение может смять ткань, испортить складки или утащить её под кожу, '
        'и в игре это будет видно.\n'
        'Очень советую: сначала просто поиграйся с кистями на любой ненужной вещи, чтобы понять, '
        'как они работают. И только потом бери лепку для своих рефитов.\n'
        'Если что-то пошло не так: Ctrl+Z или «Отменить». А «Вернуть» во вкладке «Подгонка» '
        'откатит вещь к оригиналу.',
        'Sculpting moves the cloth points by hand. It is a powerful but very delicate tool.\n'
        'One clumsy stroke can crumple the cloth, ruin the folds or pull it under the skin, '
        'and it will show in the game.\n'
        'I strongly recommend: first just play with the brushes on any item you do not need, to get a feel '
        'for how they work. Only then use sculpting for your real refits.\n'
        'If something goes wrong: Ctrl+Z or "Undo". "Reset" in the "Fit" tab brings the item back '
        'to the original.')),
    'smooth': (tr('Сглаживание - очень аккуратно', 'Smoothing - very gently'), tr(
        'Одежда очень чувствительна к сглаживанию.\n'
        '«Сгладить» легко стирает складки, швы и мелкие детали, которые автор делал вручную, '
        'и ткань становится «пластиковой».\n'
        'Работай маленькой силой (0.1-0.3), короткими мазками и только там, где правда нужно. '
        'Лучше несколько раз слегка, чем один раз сильно.\n'
        'К сглаживанию нужно приноровиться, так что сначала потренируйся на ненужной вещи.',
        'Clothing is very sensitive to smoothing.\n'
        '"Smooth" easily wipes out folds, seams and small details the author made by hand, '
        'and the cloth starts to look like plastic.\n'
        'Use low strength (0.1-0.3), short strokes and only where it is really needed. '
        'A few light passes are better than one strong one.\n'
        'Smoothing takes practice, so try it on an item you do not need first.')),
}


def tip_hidden(key):
    return key in C.load_config().get('hidden_tips', [])


def hide_tip(key):
    cfg = C.load_config()
    cfg['hidden_tips'] = sorted(set(cfg.get('hidden_tips', [])) | {key})
    C.save_config(cfg)


def show_tip(op, context, key, confirm):
    """Окно предупреждения посреди экрана; без него - сразу выполнить."""
    if tip_hidden(key) or bpy.app.background:
        return op.execute(context)
    try:
        w = context.window
        w.cursor_warp(w.width // 2, w.height // 2 + 120)  # окно Blender появляется у курсора
    except Exception:
        pass
    return context.window_manager.invoke_props_dialog(op, width=520, title=TIPS[key][0], confirm_text=confirm)


def draw_tip(lay, key, op):
    import textwrap
    col = lay.column(align=True)
    for i, par in enumerate(TIPS[key][1].split('\n')):
        if i:
            col.separator()
        for j, line in enumerate(textwrap.wrap(par, 78)):
            col.label(text=line, icon=('ERROR' if i == 0 and j == 0 else 'NONE'))
    lay.separator()
    lay.prop(op, 'dont_show')


class REFIT_OT_sculpt(bpy.types.Operator):
    bl_idname = 'refit.sculpt'
    bl_label = tr('Лепить', 'Sculpt')
    bl_description = tr('Режим лепки: Grab - тянуть, Smooth - сгладить, Inflate - надуть. Симметрия по X включена',
                        'Sculpt mode: Grab - pull, Smooth - smooth, Inflate - puff up. X symmetry is on')
    dont_show: bpy.props.BoolProperty(name=tr('Больше не показывать', "Don't show again"), default=False,
                                      options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not cloth_obj():
            return self.execute(context)  # сообщит, что сначала нужна вещь
        return show_tip(self, context, 'sculpt', tr('Понятно, начать лепку', 'Got it, start sculpting'))

    def draw(self, context):
        draw_tip(self.layout, 'sculpt', self)

    def execute(self, context):
        if self.dont_show:
            hide_tip('sculpt')
        ob = cloth_obj()
        if not ob:
            report(self, tr('Сначала загрузи вещь', 'Load an item first'), 'WARNING')
            return {'CANCELLED'}
        context.view_layer.objects.active = ob
        ob.select_set(True)
        bpy.ops.object.mode_set(mode='SCULPT')
        ob.use_mesh_mirror_x = True
        activate_brush('Grab')
        if not bpy.app.background:
            for area in context.screen.areas if context.screen else []:
                if area.type == 'VIEW_3D':
                    tidy_view(area.spaces.active)  # без полосы со всеми кистями Blender снизу
        if context.scene.refit_tab != 'SCULPT':
            context.scene.refit_tab = 'SCULPT'
        report(self, tr('Лепка: Grab - тянуть, Smooth - сгладить, Inflate - надуть. F - размер, Shift+F - сила.',
                        'Sculpt: Grab - pull, Smooth - smooth, Inflate - puff up. F - size, Shift+F - strength.'))
        return {'FINISHED'}


# ---------- проверка посадки ----------

def outward(pos, tris, index, normals):
    """Нормали оболочки, развёрнутые наружу (по нормалям кожи под ней)."""
    n = fit.vertex_normals(pos, tris)
    idx, _ = index.query(pos, 1)
    flip = (n * normals[idx[:, 0]]).sum(1) < 0
    n[flip] *= -1
    return n


class REFIT_OT_check(bpy.types.Operator):
    bl_idname = 'refit.check'
    bl_label = tr('Проверить посадку', 'Check fit')
    bl_description = tr('Красный - ткань под кожей или татуировкой, жёлтый - висит заметно дальше, чем задумал автор',
                        'Red - cloth under the skin or a tattoo, yellow - hangs noticeably further than the author intended')

    def execute(self, context):
        ob = cloth_obj()
        if not ob or state['orig'] is None:
            report(self, tr('Сначала загрузи вещь', 'Load an item first'), 'WARNING')
            return {'CANCELLED'}
        cur = get_pos(ob)
        b = body()
        prog = Progress(tr('Проверка посадки', 'Checking fit'))
        try:
            prog(20, tr('зазоры', 'gaps'))
            # Зазор до гладкой плоскости соседних точек тела. Сравнение с отдельными точками
            # давало ложное "красное" в изгибах: туда попадали точки с другой стороны тела.
            if fit.BVHTree is not None:
                # точный зазор до поверхности (а не до ближайших точек тела)
                gap, _ = b.surf_gap(cur, 0.04)
                gap0, _ = b.van_gap(state['orig'], 0.04)
            else:
                gap, _, d1 = fit.plane_gap(cur, b.surf_index, b.surf, b.n_surf)
                gap0, _, d0 = fit.plane_gap(state['orig'], b.van_index, b.van, b.n_van)
                gap[d1 > 0.04] = np.inf
                gap0[d0 > 0.04] = np.inf
            hard, hard0 = gap, gap0  # препятствия: кожа и (если выбрана) татуировка
            key = context.scene.refit_tattoo
            if key and key != 'none':
                prog(60, tr('татуировка', 'tattoo'))
                # Татуировка поверх кожи - тоже препятствие. Но и у автора ткань местами лежит под её
                # оболочкой (в игре так и задумано), такие места не считаем ошибкой подгонки.
                if fit.BVHTree is not None:
                    new_sh, van_sh = tattoo_obstacles(context)[0]
                    gt, _ = new_sh.gap(cur, 0.01)
                    gt0, _ = van_sh.gap(state['orig'], 0.01)
                    hard = np.minimum(gap, gt)
                    hard0 = np.minimum(gap0, gt0)
                else:
                    tp, _, tt, _ = tattoo_shape(key)
                    tn = outward(tp, tt, b.surf_index, b.n_surf)
                    gt, _, dt = fit.plane_gap(cur, fit.Index(tp), tp, tn)
                    hard = np.where(dt < 0.01, np.minimum(gap, gt), gap)
                    vp = b.z[key + '_van']
                    vn = outward(vp, b.z[key + '_van_tris'], b.van_index, b.n_van)
                    gt0, _, dt0 = fit.plane_gap(state['orig'], fit.Index(vp), vp, vn)
                    hard0 = np.where(dt0 < 0.01, np.minimum(gap0, gt0), gap0)
        finally:
            prog.done()
        with np.errstate(invalid='ignore'):
            inside = np.isfinite(hard) & (hard < -0.0005) & ~(np.isfinite(hard0) & (hard0 < -0.0005))
            ref = np.maximum(gap0, 0)
            base = state.get('base')
            if fit.BVHTree is not None and base is not None and len(base) == len(cur):
                # После авто-подгонки ткань местами отходит от тела нарочно: под грудью и под ягодицами
                # она натягивается мостиком. Жёлтым - только то, что висит дальше, чем положила подгонка.
                gb, _ = b.surf_gap(base, 0.04)
                ref = np.where(np.isfinite(gb), np.maximum(ref, gb), ref)
            loose = np.isfinite(gap) & np.isfinite(gap0) & (gap - ref > 0.006)
        col = np.tile(CLOTH_COLOR, (len(cur), 1))
        col[loose] = (1.0, 0.85, 0.1, 1)
        col[inside] = (1.0, 0.1, 0.1, 1)
        set_color_attr(ob, col)
        setup_view()
        report(self, tr(f'Под кожей или татуировкой (красное): {int(inside.sum())} точек, висит (жёлтое): {int(loose.sum())}. '
                        'После правки нажми ещё раз.',
                        f'Under the skin or a tattoo (red): {int(inside.sum())} points, hanging (yellow): {int(loose.sum())}. '
                        'Press again after editing.'))
        return {'FINISHED'}


# ---------- экспорт ----------

def dynamic_name(raw, rel):
    """Если мод выбирает модель по шаблону с {body}, возвращает путь модели для типа нашего тела."""
    tag = (body().info.get('tag') or '').lower()
    if not tag:
        return None
    rel_l = rel.replace('/', '\\').lower()
    folder, fname = os.path.split(rel_l)
    jdir = raw + '_json'
    if not os.path.isdir(jdir):
        return None
    for dp, _, fs in os.walk(jdir):
        for f in fs:
            if not f.lower().endswith('.json'):
                continue
            text = open(os.path.join(dp, f), encoding='utf-8', errors='ignore').read()
            for pat in set(re.findall(r'"\$value":\s*"([^"]*\{body\}[^"]*\.mesh)"', text)):
                pat = pat.replace('\\\\', '\\').lstrip('*').replace('/', '\\').lower()
                pfolder, pname = os.path.split(pat)
                if pfolder != folder:
                    continue
                rx = '^' + re.sub(r'\\\{[a-z0-9_.]+\\\}', '(.+?)', re.escape(pname)) + '$'
                mt = re.match(rx, fname)
                if not mt:
                    continue
                tokens = re.findall(r'\{([a-z0-9_.]+)\}', pname)
                out = pname
                for tok, val in zip(tokens, mt.groups()):
                    out = out.replace('{' + tok + '}', tag if tok == 'body' else val, 1)
                return os.path.join(folder, out)
    return None


def xl_patches(mod, rel):
    """Ключи resource.patch из .xl мода, в списках которых есть эта модель (подключение материалов)."""
    target = rel.replace('/', '\\').lower()
    found = []
    for x in mod.get('xls', []):
        key = None
        for line in open(x, encoding='utf-8', errors='ignore'):
            s = line.strip()
            if s.endswith(':') and s.lower().endswith('.mesh:'):
                key = s[:-1]
            elif s.startswith('-') and key and s[1:].strip().lower() == target:
                found.append(key)
    return found


def body_short():
    b = body().info
    return C.safe(b.get('tag') or C.clean_mod_name(b['name']), 16)


def bake_mesh(jpath, results, tmp):
    """Подогнанные позиции -> готовый файл tmp\\item.mesh (то, что потом кладём в архив)."""
    m = MeshPos(jpath)
    fit.apply_positions(m, results)
    os.makedirs(tmp, exist_ok=True)
    m.save(os.path.join(tmp, 'item.mesh.json'))
    C.deserialize(os.path.join(tmp, 'item.mesh.json'), tmp)
    return os.path.join(tmp, 'item.mesh')


def build_zip(mod, raw, items, zip_name, prog=None, dynamic=True):
    """items: [(rel, mesh_json_path, [позиции по всем чанкам])] -> один zip с рефитом."""
    out_dir = os.path.join(mod_work(mod) if mod else os.path.join(C.WORK, 'tattoo'), 'out')
    C.rmtree(out_dir)
    arch_name = '#REFIT_' + body_short() + '_' + C.safe(C.clean_mod_name(mod['name']) if mod else 'tattoos', 24)
    pack_root = os.path.join(out_dir, 'p', arch_name)
    xl = {}
    for n, (rel, jpath, results) in enumerate(items):
        if prog:
            prog(60 + 30 * n / max(len(items), 1), tr('сборка ', 'building ') + os.path.basename(rel))
        tmp = os.path.join(out_dir, f'i{n}')
        bake_mesh(jpath, results, tmp)
        rel = rel.replace('/', '\\')
        dyn = dynamic_name(raw, rel) if dynamic else None
        target = dyn or rel
        os.makedirs(C.lp(os.path.join(pack_root, os.path.dirname(target))), exist_ok=True)
        shutil.copyfile(os.path.join(tmp, 'item.mesh'), C.lp(os.path.join(pack_root, target)))
        if dyn:
            # Новая модель под тип нашего тела: материалы подключаем так же, как у оригинала
            for k in xl_patches(mod, rel):
                xl.setdefault(k, []).append(dyn)
    if prog:
        prog(92, tr('упаковка архива', 'packing the archive'))
    C.wk('pack', pack_root, '-o', os.path.join(out_dir, 'p'))
    os.makedirs(C.EXPORTS, exist_ok=True)
    zip_path = os.path.join(C.EXPORTS, C.fs_name(zip_name)[:150] + '.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(pack_root + '.archive', 'archive/pc/mod/' + arch_name + '.archive')
        if xl:
            lines = [f'# Refit Studio: refit for {body_label()}, materials as in the original models',
                     'resource:', '    patch:']
            for k, vals in xl.items():
                lines.append(f'        {k}:')
                lines += [f'           - {v}' for v in vals]
            z.writestr('archive/pc/mod/' + arch_name + '.xl', '\n'.join(lines) + '\n')
    return zip_path


def item_results(jpath, lod0_new, lod0_orig, ranges):
    """Позиции для всех чанков: LOD0 из правки, остальные LOD - перенос правок."""
    m = MeshPos(jpath)
    r = {ci: (a, b) for ci, a, b in ranges}
    out = []
    for ci in range(len(m.chunks)):
        if ci in r:
            out.append(lod0_new[r[ci][0]:r[ci][1]])
        else:
            out.append(fit.transfer(lod0_orig, lod0_new, m.read(ci)))
    return out


def zip_title(item=None):
    t = f'{C.clean_mod_name(body_label())} refit - {C.clean_mod_name(state["mod"]["name"])[:50]}'
    return t + (f' - {item}' if item else tr(' (весь мод)', ' (whole mod)'))


class UserError(Exception):
    """Понятная ошибка для панели (без «подробностей в логе»)."""


def item_fit(prog):
    """Позиции загруженной вещи с правками для всех LOD."""
    ob = cloth_obj()
    if not ob or state['json'] is None:
        raise UserError(tr('Сначала загрузи вещь', 'Load an item first'))
    new = get_pos(ob)
    if len(new) != len(state['orig']):
        raise UserError(tr('Число точек изменилось (Dyntopo/Remesh/удаление?). Так игра модель не примет. '
                           'Нажми «Вернуть оригинал» и правь только перемещением точек.',
                           'The number of points changed (Dyntopo/Remesh/delete?). The game will not accept that. '
                           'Press "Reset to original" and only move points.'))
    prog(20, 'LOD')
    return item_results(state['json'], new, state['orig'], state['ranges'])


def make_item(context, prog):
    """Рефит загруженной вещи -> zip во внутренней папке экспорта."""
    res = item_fit(prog)
    item = os.path.splitext(os.path.basename(state['mesh']))[0]
    path = build_zip(state['mod'], state['raw'], [(state['mesh'], state['json'], res)], zip_title(item), prog)
    note = ''
    if author_has_version(state['raw'], state['mesh']):
        note = tr(' (внимание: у автора мода уже есть своя версия этой вещи под твоё тело - рефит её заменит)',
                  " (note: the mod author already has a version of this item for your body - the refit will replace it)")
    return path, tr('вещь ', 'item ') + item + note


def author_has_version(raw, rel):
    """У автора мода уже есть модель этой вещи под тип нашего тела (через шаблон {body})."""
    dyn = dynamic_name(raw, rel.replace('/', os.sep))
    return bool(dyn) and os.path.isfile(C.lp(os.path.join(raw, dyn)))


def make_mod(context, prog):
    """Авто-подгонка всех женских вещей мода под обычное тело (★) -> один zip."""
    if not state['mod']:
        raise UserError(tr('Сначала выбери мод одежды', 'Choose a clothing mod first'))
    picks = [m for m in state['meshes'] if body_kind(m) == 'base' and looks_female(m)]
    if not picks:
        picks = [m for m in state['meshes'] if looks_female(m) and body_kind(m) not in ('other', 'this')]
    if not picks:
        raise UserError(tr('Не нашёл в моде женских вещей под обычное тело. Выбери вещь вручную.',
                           'No female items for the vanilla body found in this mod. Choose an item manually.'))
    # вещи, которые автор уже сделал под это тело, не трогаем: его ручная работа лучше авто-подгонки
    own = [m for m in picks if author_has_version(state['raw'], m)]
    picks = [m for m in picks if m not in own]
    if not picks:
        raise UserError(tr('У автора мода уже есть версии всех вещей под твоё тело - рефит не нужен. '
                           'Если хочешь свою подгонку, выбери вещь и экспортируй её отдельно.',
                           'The mod author already has versions of all items for your body - no refit needed. '
                           'If you want your own fit, choose an item and export it separately.'))
    items = []
    bdir = os.path.join(mod_work(state['mod']), 'batch')
    C.rmtree(bdir)
    os.makedirs(bdir)
    for n, rel in enumerate(picks):
        prog(5 + 55 * n / len(picks), f'{n + 1}/{len(picks)} {os.path.basename(rel)}')
        src = os.path.join(bdir, f'{n}.mesh')
        shutil.copyfile(C.lp(os.path.join(state['raw'], rel)), src)
        jpath = C.serialize(src, bdir)
        if not has_geometry(jpath):
            continue
        m = MeshPos(jpath)
        items.append((rel, jpath, [fit_points(m.read(ci), context, m.triangles(ci)) for ci in range(len(m.chunks))]))
    path = build_zip(state['mod'], state['raw'], items, zip_title(), prog)
    names = ', '.join(os.path.basename(r)[:-5] for r, _, _ in items)
    skip = (tr('; пропущено (у автора уже есть под твоё тело): ', '; skipped (author already has them for your body): ')
            + str(len(own))) if own else ''
    return path, tr('весь мод, вещей: ', 'whole mod, items: ') + f'{len(items)} ({names}){skip}'


def make_tattoos(context, prog):
    """5 татуировок тела из игры, подогнанные под выбранное тело -> zip (заменяет игровые)."""
    b = body()
    keys = [k for k, has_body in b.tattoos() if not has_body]
    if not keys:
        raise UserError(tr('У этого тела уже есть свои татуировки, рефит не нужен.',
                           'This body already has its own tattoos, no refit needed.'))
    src = C.vanilla_jsons()  # пересоздаются, если сменилась версия WolvenKit
    tdir = os.path.join(C.WORK, 'tattoo')
    C.rmtree(tdir)
    os.makedirs(tdir)
    items, lod0 = [], {}
    for n, k in enumerate(keys):
        prog(5 + 50 * n / len(keys), k)
        jpath = os.path.join(tdir, k + '.mesh.json')
        shutil.copyfile(src[k], jpath)
        m = MeshPos(jpath)
        res = [fit.autofit(m.read(ci), b) for ci in range(len(m.chunks))]
        items.append((C.TATTOO_FILES[k], jpath, res))
        lod0[k] = np.concatenate([res[ci] for ci in range(len(m.chunks)) if m.lod_mask(ci) & 1])
    path = build_zip(None, None, items, f'{C.clean_mod_name(body_label())} refit - Body Tattoos', prog,
                     dynamic=False)
    # запоминаем форму татуировок: теперь одежда под них подгоняется полностью
    np.savez_compressed(os.path.join(b.folder, 'tattoo_refit.npz'), **lod0)
    B.pop('tattoo_refit', None)
    B.pop('obstacles', None)  # оболочки татуировок теперь другие
    show_tattoo(context.scene.refit_tattoo)
    return path, tr('татуировки тела; после установки выбирай татуировку в списке - одежда подгоняется полностью',
                    'body tattoos; after installing, pick your tattoo in the list - clothing is then fitted fully')


MAKERS = {'ITEM': make_item, 'MOD': make_mod, 'TATTOO': make_tattoos}


def run_export(context, title):
    prog = Progress(title)
    try:
        return MAKERS[context.scene.refit_scope](context, prog)
    finally:
        prog.done()


def default_zip_name(context):
    scope = context.scene.refit_scope
    if scope == 'TATTOO':
        return f'{C.clean_mod_name(body_label())} refit - Body Tattoos'
    if not state['mod']:
        return 'refit'
    if scope == 'ITEM' and state['mesh']:
        return zip_title(os.path.splitext(os.path.basename(state['mesh']))[0])
    return zip_title()


class REFIT_OT_export_zip(bpy.types.Operator):
    bl_idname = 'refit.export_zip'
    bl_label = tr('Сохранить zip…', 'Save zip…')
    bl_description = tr('Собрать рефит и сохранить zip в папку, которую выберешь',
                        'Build the refit and save the zip to a folder of your choice')
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default='*.zip', options={'HIDDEN'})

    def invoke(self, context, event):
        self.filepath = os.path.join(C.output_dir(), C.fs_name(default_zip_name(context))[:150] + '.zip')
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        dest = self.filepath or os.path.join(C.output_dir(), C.fs_name(default_zip_name(context))[:150] + '.zip')
        if not dest.lower().endswith('.zip'):
            dest += '.zip'
        path, what = run_export(context, tr('Сохраняю zip', 'Saving zip'))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(path, dest)
        cfg = C.load_config()
        if not os.environ.get('REFIT_OUTPUT') and cfg.get('output') != os.path.dirname(dest):
            cfg['output'] = os.path.dirname(dest)  # в следующий раз предложим ту же папку
            C.save_config(cfg)
        report(self, tr('Сохранено', 'Saved') + f' ({what}): {dest}')
        return {'FINISHED'}


class REFIT_OT_export_vortex(bpy.types.Operator):
    bl_idname = 'refit.export_vortex'
    bl_label = tr('В Vortex', 'To Vortex')
    bl_description = tr('Собрать рефит и сразу отдать его Vortex на установку. Vortex ставит мод в игру, '
                        'которая сейчас выбрана в нём, - там должен быть Cyberpunk 2077',
                        'Build the refit and hand it straight to Vortex to install. Vortex installs it into the '
                        'game that is active in Vortex - that must be Cyberpunk 2077')

    def execute(self, context):
        vortex = C.find_vortex()
        if not vortex:
            raise UserError(tr('Не нашёл Vortex. Сохрани zip кнопкой «Сохранить zip…» и перетащи его в Vortex вручную.',
                               'Vortex not found. Save the zip with "Save zip…" and drag it into Vortex manually.'))
        path, what = run_export(context, tr('Отправляю в Vortex', 'Sending to Vortex'))
        C.send_to_vortex(vortex, path)
        report(self, tr(f'Отправлено в Vortex ({what}). Если Vortex спросит - подтверди установку, '
                        'и проверь, что мод включён (Enabled).',
                        f'Sent to Vortex ({what}). If Vortex asks, confirm the install '
                        'and make sure the mod is Enabled.'))
        return {'FINISHED'}


# ---------- экспорт для мододелов: голый .mesh под своим именем ----------

BODY_SUFFIXES = sorted(set(('base_body', 'basebody', 'vanilla', 'base') + OTHER_BODIES), key=len, reverse=True)


def body_slug():
    b = body().info
    s = re.sub(r'[^a-z0-9]+', '_', (b.get('tag') or C.clean_mod_name(b['name'])).lower()).strip('_')
    return s[:24] or 'refit'


def default_mesh_name():
    """Имя для .mesh: тело в конце имени меняем на наше (..._w_base_body -> ..._w_slim_thin), иначе дописываем."""
    if not state['mesh']:
        return 'refit'
    dyn = dynamic_name(state['raw'], state['mesh'].replace('/', os.sep)) if state['raw'] else None
    if dyn:
        return os.path.splitext(os.path.basename(dyn))[0]  # мод сам выбирает модель по телу - его шаблон
    name = os.path.splitext(os.path.basename(state['mesh']))[0]
    tag, low = body_slug(), name.lower()
    for suf in BODY_SUFFIXES:
        mt = re.search(r'([_\-.])' + re.escape(suf) + r'$', low)
        if mt:
            return name[:mt.start()] + mt.group(1) + tag
    return name if low.endswith(tag) else name + '_' + tag


class REFIT_OT_export_mesh(bpy.types.Operator):
    bl_idname = 'refit.export_mesh'
    bl_label = tr('Сохранить .mesh…', 'Save .mesh…')
    bl_description = tr('Только файл модели загруженной вещи, под любым именем, без архива. '
                        'Для своего проекта WolvenKit: путь и материалы (.xl) подключаешь сам',
                        'Only the model file of the loaded item, with any name, no archive. '
                        'For your own WolvenKit project: you set up the path and materials (.xl) yourself')
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default='*.mesh', options={'HIDDEN'})

    def invoke(self, context, event):
        name = C.fs_name(context.scene.refit_mesh_name.strip() or default_mesh_name())[:150]
        self.filepath = os.path.join(C.output_dir(), name + '.mesh')
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if state['json'] is None:
            raise UserError(tr('Сначала загрузи вещь', 'Load an item first'))
        dest = self.filepath or os.path.join(C.output_dir(), C.fs_name(default_mesh_name())[:150] + '.mesh')
        if os.path.isdir(dest) or not os.path.basename(dest):
            dest = os.path.join(dest, C.fs_name(default_mesh_name())[:150] + '.mesh')
        if not dest.lower().endswith('.mesh'):
            dest += '.mesh'
        prog = Progress(tr('Сохраняю .mesh', 'Saving .mesh'))
        try:
            res = item_fit(prog)
            prog(60, tr('сборка модели', 'building the model'))
            tmp = os.path.join(mod_work(state['mod']), 'mesh_out')
            C.rmtree(tmp)
            path = bake_mesh(state['json'], res, tmp)
        finally:
            prog.done()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(path, C.lp(dest))
        cfg = C.load_config()
        if not os.environ.get('REFIT_OUTPUT') and cfg.get('output') != os.path.dirname(dest):
            cfg['output'] = os.path.dirname(dest)
            C.save_config(cfg)
        note = ''
        if state['mod'] and xl_patches(state['mod'], state['mesh']):
            note = tr('. Материалы у этой вещи подключаются через .xl мода - добавь новое имя в свой .xl',
                      ". This item's materials come from the mod's .xl - add the new name to your own .xl")
        report(self, tr('Сохранено', 'Saved') + f': {dest}{note}')
        return {'FINISHED'}


class REFIT_OT_export_menu(bpy.types.Operator):
    bl_idname = 'refit.export_menu'
    bl_label = tr('Экспорт…', 'Export…')
    bl_description = tr('Все способы экспорта: в Vortex, в zip или для мододелов',
                        'All export options: to Vortex, to a zip or for modders')

    def invoke(self, context, event):
        sc = context.scene
        if state['mesh']:
            try:
                sc.refit_mesh_name = default_mesh_name()
            except Exception:
                C.log('mesh name:\n' + traceback.format_exc())
        return context.window_manager.invoke_popup(self, width=330)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        self.layout.label(text=tr('Экспорт', 'Export'), icon='EXPORT')
        draw_export(self.layout, context)


def draw_export(lay, context):
    """Все способы экспорта: во всплывающем окне и во вкладке «Экспорт»."""
    sc = context.scene
    lay.label(text=tr('Что экспортировать:', 'What to export:'))
    lay.row().prop(sc, 'refit_scope', expand=True)
    lay.separator()
    lay.label(text=tr('Для игроков', 'For players'))
    col = lay.column(align=True)
    col.scale_y = 1.3
    col.operator('refit.export_vortex', text=tr('Установить в Vortex', 'Install to Vortex'), icon='PACKAGE')
    col.operator('refit.export_zip', icon='FILE_ARCHIVE')
    lay.separator()
    opened = sc.refit_modder_open
    lay.prop(sc, 'refit_modder_open', text=tr('Для мододелов', 'For modders'), emboss=False,
             icon='TRIA_DOWN' if opened else 'TRIA_RIGHT')
    if not opened:
        return
    box = lay.box()
    if sc.refit_scope != 'ITEM' or state['json'] is None:
        box.label(text=tr('Только для режима «Вещь»', 'Only in "Item" mode'), icon='INFO')
        box.label(text=tr('с загруженной вещью', 'with an item loaded'))
        return
    box.prop(sc, 'refit_mesh_name', text=tr('Имя', 'Name'))
    box.operator('refit.export_mesh', icon='MESH_DATA')
    box.label(text=tr('Только файл модели, без архива', 'Model file only, no archive'))
    box.label(text=tr('Путь и материалы - в своём WolvenKit', 'Path and materials - in your WolvenKit'))


# ---------- сохранение работы ----------

def save_items(self, context):
    return C_keep('saves', [(str(i), s, '') for i, s in enumerate(state['saves'])])


class REFIT_OT_save(bpy.types.Operator):
    bl_idname = 'refit.save'
    bl_label = tr('Сохранить работу', 'Save work')

    def execute(self, context):
        ob = cloth_obj()
        if not ob or state['json'] is None:
            report(self, tr('Нечего сохранять: сначала загрузи вещь', 'Nothing to save: load an item first'), 'WARNING')
            return {'CANCELLED'}
        get_pos(ob)  # выйти из режима лепки
        name = C.safe(C.clean_mod_name(state['mod']['name']), 30) + '__' + \
            C.safe(os.path.splitext(os.path.basename(state['mesh']))[0], 40)
        d = os.path.join(C.SAVES, name)
        os.makedirs(d, exist_ok=True)
        # копия данных вещи: рабочая папка мода перезаписывается при загрузке другой вещи
        if os.path.abspath(state['json']) != os.path.abspath(os.path.join(d, 'item.mesh.json')):
            shutil.copyfile(state['json'], os.path.join(d, 'item.mesh.json'))
        np.save(os.path.join(d, 'orig.npy'), state['orig'])
        if state.get('base') is not None:
            np.save(os.path.join(d, 'base.npy'), state['base'])
        elif os.path.exists(os.path.join(d, 'base.npy')):
            os.remove(os.path.join(d, 'base.npy'))
        sc = context.scene
        sc['refit_save'] = json.dumps({'mod': state['mod'], 'mesh': state['mesh'], 'raw': state['raw'],
                                       'json': os.path.join(d, 'item.mesh.json'), 'orig': os.path.join(d, 'orig.npy'),
                                       'ranges': state['ranges'], 'profile': body().info['id']})
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(d, 'work.blend'), check_existing=False)
        report(self, tr(f'Сохранено: {name}. Открыть потом - «Открыть сохранённую».',
                        f'Saved: {name}. Open it later with "Open saved".'))
        return {'FINISHED'}


class REFIT_OT_open(bpy.types.Operator):
    bl_idname = 'refit.open'
    bl_label = tr('Открыть сохранённую', 'Open saved')
    bl_property = 'save'
    save: bpy.props.EnumProperty(items=save_items)

    def invoke(self, context, event):
        state['saves'] = sorted(d for d in os.listdir(C.SAVES)
                                if os.path.exists(os.path.join(C.SAVES, d, 'work.blend'))) if os.path.isdir(C.SAVES) else []
        if not state['saves']:
            report(self, tr('Сохранённых работ пока нет', 'No saved work yet'), 'WARNING')
            return {'CANCELLED'}
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        bpy.ops.wm.open_mainfile(filepath=os.path.join(C.SAVES, state['saves'][int(self.save)], 'work.blend'))
        return {'FINISHED'}


@persistent
def restore_state(_):
    """После открытия сохранения восстанавливаем, какая вещь и откуда загружена."""
    sc = bpy.context.scene
    data = sc.get('refit_save')
    if not data:
        return
    d = json.loads(data)
    other_body = bool(d.get('profile')) and d['profile'] != body().info['id']
    if other_body:
        sc.refit_status = tr('Внимание: эта работа сделана под другое тело. Экспорт будет под текущее тело - '
                             'при необходимости переключи тело в лаунчере.',
                             'Note: this work was made for another body. Export will use the current body - '
                             'switch the body in the launcher if needed.')
    base_path = os.path.join(os.path.dirname(d['orig']), 'base.npy')
    state.update(mod=d['mod'], mesh=d['mesh'], raw=d['raw'], json=d['json'],
                 orig=np.load(d['orig']), ranges=[tuple(r) for r in d['ranges']],
                 base=np.load(base_path) if os.path.exists(base_path) else None)
    if d['raw'] and os.path.isdir(d['raw']):
        state['meshes'] = sorted(os.path.relpath(os.path.join(dp, f), d['raw'])
                                 for dp, _, fs in os.walk(d['raw']) for f in fs if f.lower().endswith('.mesh'))
    if not other_body:
        sc.refit_status = tr('Работа открыта: ', 'Work opened: ') + os.path.basename(d['mesh']) + \
            tr('. Продолжай правку.', '. Continue editing.')
    bpy.app.timers.register(lambda: (setup_view(), None)[1], first_interval=0.3)


# ---------- оформление: цвета лаунчера, без лишнего Blender ----------
# Цвета ставим только на время мастерской: автосохранение настроек Blender выключено,
# поэтому в обычном Blender у человека всё останется как было.

# палитра «киберпанк»: почти чёрный фон, жёлтый неон - главные кнопки, бирюза - выбранное
PAL = {'bg': '0D0D14', 'card': '16161F', 'btn': '1E1E2A', 'btn_hi': '2A2A38', 'line': '2A2A38',
       'text': 'F2F2F5', 'dim': '8E8EA3', 'acc': 'FCEE0A', 'sel': '02D7F2', 'view': '0A0A10'}
_ui = {'focused': False, 'header': None}


def rgb(key):
    h = PAL[key]
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def set_col(obj, attr, key, alpha=1.0):
    try:
        cur = getattr(obj, attr)
        c = rgb(key)
        setattr(obj, attr, c + (alpha,) if len(cur) == 4 else c)
    except Exception:
        pass


def apply_theme():
    prefs = bpy.context.preferences
    try:
        prefs.use_preferences_save = False
    except Exception:
        pass
    th = prefs.themes[0]
    ui = th.user_interface
    for w in (ui.wcol_regular, ui.wcol_tool, ui.wcol_toggle, ui.wcol_radio, ui.wcol_option, ui.wcol_num,
              ui.wcol_numslider, ui.wcol_text, ui.wcol_menu, ui.wcol_pulldown, ui.wcol_tab, ui.wcol_list_item):
        set_col(w, 'inner', 'btn')
        set_col(w, 'inner_sel', 'acc')
        set_col(w, 'outline', 'line')
        set_col(w, 'outline_sel', 'acc')
        set_col(w, 'text', 'text')
        set_col(w, 'text_sel', 'bg')
        set_col(w, 'item', 'acc')
        try:
            w.show_shaded = False
            w.roundness = 1.0
        except Exception:
            pass
    for w in (ui.wcol_text, ui.wcol_option, ui.wcol_num, ui.wcol_numslider, ui.wcol_menu, ui.wcol_list_item):
        try:
            w.roundness = 0.45
        except Exception:
            pass
    try:
        ui.panel_roundness = 0.6
    except Exception:
        pass
    set_col(ui.wcol_text, 'inner', 'bg')
    # выбранное (вкладки, выбранная кисть, пункты списков и меню, галочки) - синее с белым текстом;
    # оранжевыми остаются только главные кнопки (wcol_tool с depress)
    for w in (ui.wcol_radio, ui.wcol_tab, ui.wcol_list_item, ui.wcol_menu_item, ui.wcol_option, ui.wcol_toggle,
              ui.wcol_regular):
        set_col(w, 'inner_sel', 'sel')
        set_col(w, 'outline_sel', 'sel')
        set_col(w, 'text_sel', 'bg')
    # жёлтый фон с тёмным текстом - только у кнопок и вкладок; у галочек и переключателей текст светлый
    for w in (ui.wcol_text, ui.wcol_option, ui.wcol_regular, ui.wcol_toggle, ui.wcol_num, ui.wcol_numslider):
        set_col(w, 'text_sel', 'text')
    set_col(ui.wcol_numslider, 'item', 'btn_hi')
    set_col(ui.wcol_option, 'item', 'bg')
    set_col(ui.wcol_box, 'inner', 'btn')
    set_col(ui.wcol_box, 'outline', 'line')
    for w in (ui.wcol_menu_back, ui.wcol_tooltip):
        set_col(w, 'inner', 'card')
        set_col(w, 'outline', 'line')
        set_col(w, 'text', 'text')
    set_col(ui.wcol_menu_item, 'inner_sel', 'sel')
    set_col(ui.wcol_menu_item, 'text', 'text')
    set_col(ui.wcol_menu_item, 'text_sel', 'bg')
    for a, k in (('panel_back', 'card'), ('panel_sub_back', 'card'), ('panel_header', 'card'),
                 ('panel_title', 'text'), ('panel_text', 'text'), ('panel_outline', 'line'), ('panel_active', 'sel')):
        set_col(ui, a, k)
    set_col(th.regions.sidebars, 'back', 'card')
    set_col(th.regions.sidebars, 'tab_back', 'bg')
    sp = th.view_3d.space
    try:
        sp.gradients.background_type = 'SINGLE_COLOR'
    except Exception:
        pass
    set_col(sp.gradients, 'high_gradient', 'view')
    for a, k in (('header', 'bg'), ('header_text', 'text'), ('header_text_hi', 'sel'), ('text', 'text'),
                 ('text_hi', 'sel'), ('title', 'text')):
        set_col(sp, a, k)
    set_col(th.view_3d, 'object_active', 'acc')


def focus_view():
    """Только 3D-вид: без верхнего меню, строки состояния, таймлайна и лишних окон Blender."""
    if _ui['focused']:
        return
    for w in bpy.context.window_manager.windows:
        if w.screen.show_fullscreen:
            _ui['focused'] = True
            return
        for a in w.screen.areas:
            if a.type != 'VIEW_3D':
                continue
            region = next((r for r in a.regions if r.type == 'WINDOW'), None)
            try:
                with bpy.context.temp_override(window=w, area=a, region=region):
                    bpy.ops.screen.screen_full_area(use_hide_panels=True)
                _ui['focused'] = True
            except Exception:
                C.log('focus view:\n' + traceback.format_exc())
            return


def tidy_view(sp):
    for attr, val in (('show_region_toolbar', False), ('show_region_tool_header', False),
                      ('show_region_asset_shelf', False), ('show_region_header', True), ('show_region_ui', True)):
        try:
            setattr(sp, attr, val)
        except Exception:
            pass
    for attr in ('show_floor', 'show_axis_x', 'show_axis_y', 'show_cursor', 'show_text', 'show_stats',
                 'show_object_origins'):
        try:
            setattr(sp.overlay, attr, False)
        except Exception:
            pass


def header_draw(self, context):
    """Своя верхняя полоса вместо меню Blender."""
    sc = context.scene
    lay = self.layout
    lay.label(text='REFIT STUDIO', icon='MOD_CLOTH')
    lay.separator()
    lay.label(text=tr('Тело: ', 'Body: ') + (sc.refit_body or '?'))
    if sc.refit_mesh:
        lay.label(text=tr('Вещь: ', 'Item: ') + friendly(sc.refit_mesh)[:40])
    if context.mode == 'SCULPT':
        lay.label(text=tr('· лепка', '· sculpting'), icon='SCULPTMODE_HLT')
    lay.separator_spacer()
    lay.operator('refit.save', text=tr('Сохранить работу', 'Save work'), icon='FILE_TICK')
    lay.operator('refit.open', text=tr('Открыть', 'Open'), icon='FILE_FOLDER')
    lay.operator('refit.export_menu', text=tr('ЭКСПОРТ', 'EXPORT'), icon='EXPORT', depress=True)


def install_header():
    if _ui['header'] is None:
        _ui['header'] = bpy.types.VIEW3D_HT_header.draw
        bpy.types.VIEW3D_HT_header.draw = header_draw


def window_title():
    """«Refit Studio — тело» в заголовке окна вместо «Blender». Blender иногда возвращает своё - ставим снова."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        pid, title = os.getpid(), f'Refit Studio — {body_label()}'
        buf = ctypes.create_unicode_buffer(256)

        def cb(h, _):
            p = wintypes.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and u.IsWindowVisible(h):
                u.GetClassNameW(h, buf, 256)
                if buf.value.startswith('GHOST'):
                    u.GetWindowTextW(h, buf, 256)
                    if buf.value != title:
                        u.SetWindowTextW(h, title)
            return True
        u.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    except Exception:
        pass
    return 2.0


# ---------- лепка: только нужные кисти ----------

BRUSHES = (('Grab', tr('Тянуть', 'Grab'), tr('Тянуть ткань мышкой', 'Pull the cloth with the mouse')),
           ('Smooth', tr('Сгладить', 'Smooth'), tr('Сгладить складки и бугры', 'Smooth out folds and bumps')),
           ('Inflate/Deflate', tr('Надуть', 'Inflate'),
            tr('Отодвинуть ткань от тела (с Ctrl - прижать)', 'Push the cloth away from the body (Ctrl - pull in)')))


def current_brush():
    try:
        b = bpy.context.tool_settings.sculpt.brush
        return b.name.split('.')[0] if b else ''  # у кисти из библиотеки бывает «Grab.001»
    except Exception:
        return ''


def _activate(name):
    for call in (lambda: bpy.ops.brush.asset_activate(
                     asset_library_type='ESSENTIALS',
                     relative_asset_identifier='brushes\\essentials_brushes-mesh_sculpt.blend\\Brush\\' + name),
                 lambda: bpy.ops.wm.tool_set_by_id(name='builtin_brush.' + name.split('/')[0])):
        try:
            call()
            return True
        except Exception:
            pass
    return False


def activate_brush(name):
    """При первом входе в лепку Blender ещё догружает библиотеку кистей - тогда пробуем ещё раз чуть позже.
    Заодно снова прячем полосу со всеми кистями, которую Blender включает после смены режима."""
    _activate(name)
    if bpy.app.background:
        return
    tries = [0]

    def retry():
        tries[0] += 1
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == 'VIEW_3D':
                    tidy_view(a.spaces.active)
                    a.tag_redraw()
        if bpy.context.mode != 'SCULPT' or current_brush() == name or tries[0] > 15:
            return None
        win = bpy.context.window_manager.windows[0]
        area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
        if area:
            with bpy.context.temp_override(window=win, area=area):
                _activate(name)
        return 0.3
    bpy.app.timers.register(retry, first_interval=0.2)


class REFIT_OT_brush(bpy.types.Operator):
    bl_idname = 'refit.brush'
    bl_label = tr('Кисть', 'Brush')
    bl_description = tr('Выбрать кисть', 'Choose a brush')
    name: bpy.props.StringProperty()
    dont_show: bpy.props.BoolProperty(name=tr('Больше не показывать', "Don't show again"), default=False,
                                      options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, props):
        return next((d for n, _, d in BRUSHES if n == props.name), cls.bl_description)

    def invoke(self, context, event):
        if self.name == 'Smooth' and current_brush() != 'Smooth':
            return show_tip(self, context, 'smooth', tr('Понятно, взять «Сгладить»', 'Got it, use Smooth'))
        return self.execute(context)

    def draw(self, context):
        draw_tip(self.layout, 'smooth', self)

    def execute(self, context):
        if self.dont_show and self.name == 'Smooth':
            hide_tip('smooth')
        if context.mode != 'SCULPT':
            bpy.ops.refit.sculpt()
        activate_brush(self.name)
        return {'FINISHED'}


class REFIT_OT_sculpt_done(bpy.types.Operator):
    bl_idname = 'refit.sculpt_done'
    bl_label = tr('Готово', 'Done')
    bl_description = tr('Закончить лепку и вернуться к подгонке', 'Finish sculpting and go back to fitting')

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.scene.refit_tab = 'FIT'
        report(self, tr('Лепка закончена. Нажми «Проверить», чтобы посмотреть результат.',
                        'Sculpting done. Press "Check fit" to see the result.'))
        return {'FINISHED'}


def on_tab(self, context):
    # ушли из вкладки «Лепка» - выходим из режима лепки, чтобы кнопки подгонки работали
    if self.refit_tab != 'SCULPT' and context.mode == 'SCULPT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass


# ---------- панель ----------

def big(lay, scale=1.4):
    r = lay.row(align=True)
    r.scale_y = scale
    return r


class REFIT_PT_panel(bpy.types.Panel):
    bl_label = 'Refit Studio'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TAB
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        sc = context.scene
        lay = self.layout
        big(lay, 1.5).prop(sc, 'refit_tab', expand=True)
        lay.separator()
        {'FIT': self.draw_fit, 'SCULPT': self.draw_sculpt, 'EXPORT': self.draw_export}[sc.refit_tab](lay, context)
        if sc.refit_status:
            lay.separator()
            box = lay.box()
            words, line = sc.refit_status.split(' '), ''
            for w in words:
                if len(line) + len(w) > 34:
                    box.label(text=line)
                    line = ''
                line += w + ' '
            if line.strip():
                box.label(text=line)

    def draw_fit(self, lay, context):
        sc = context.scene
        box = lay.box()
        box.label(text=tr('Тело: ', 'Body: ') + (sc.refit_body or '?'), icon='OUTLINER_OB_ARMATURE')
        box.prop(sc, 'refit_tattoo', text='')
        lay.label(text=tr('Мод одежды', 'Clothing mod'))
        row = big(lay, 1.3)
        row.operator('refit.choose_mod', text=C.clean_mod_name(sc.refit_mod)[:34] if sc.refit_mod
                     else tr('Выбрать мод одежды', 'Choose clothing mod'), icon='FILE_FOLDER')
        row.operator('refit.add_mod', text='', icon='ADD')
        row.operator('refit.remove_mod', text='', icon='REMOVE')
        lay.prop(sc, 'refit_all_mods')
        lay.label(text=tr('Вещь', 'Item'))
        big(lay, 1.3).operator('refit.choose_mesh', text=friendly(sc.refit_mesh)[:38] if sc.refit_mesh
                               else tr('Выбрать вещь', 'Choose item'), icon='MOD_CLOTH')
        lay.separator()
        lay.prop(sc, 'refit_anchor')
        big(lay, 1.8).operator('refit.autofit', text=tr('АВТО-ПОДГОНКА', 'AUTO FIT'), icon='AUTO', depress=True)
        row = big(lay, 1.2)
        row.operator('refit.check', text=tr('Проверить', 'Check fit'), icon='VIEWZOOM')
        row.operator('refit.reset', text=tr('Вернуть', 'Reset'), icon='LOOP_BACK')
        lay.separator()
        hint = lay.box()
        if not sc.refit_mesh:
            hint.label(text=tr('Дальше: выбери мод и вещь со ★', 'Next: choose a mod and an item marked ★'),
                       icon='INFO')
        else:
            hint.label(text=tr('Дальше: «Авто-подгонка», потом', 'Next: "Auto fit", then'), icon='INFO')
            hint.label(text=tr('«Проверить». Красное - во вкладке «Лепка»', '"Check fit". Fix red in "Sculpt"'))

    def draw_sculpt(self, lay, context):
        ob = cloth_obj()
        if context.mode != 'SCULPT':
            lay.label(text=tr('Ручная правка ткани кистями', 'Touch up the cloth with brushes'))
            big(lay, 1.8).operator('refit.sculpt', text=tr('НАЧАТЬ ЛЕПКУ', 'START SCULPTING'),
                                   icon='SCULPTMODE_HLT', depress=True)
            if not ob:
                lay.label(text=tr('Сначала загрузи вещь во вкладке «Подгонка»', 'Load an item in "Fit" first'),
                          icon='INFO')
            return
        ts = context.tool_settings.sculpt
        brush = ts.brush
        cur = current_brush()
        row = big(lay, 2.0)
        for name, label, _ in BRUSHES:
            row.operator('refit.brush', text=label, depress=(cur == name)).name = name
        if brush:
            ups = ts.unified_paint_settings
            col = lay.column(align=True)
            col.prop(ups if ups.use_unified_size else brush, 'size', text=tr('Размер кисти', 'Brush size'))
            col.prop(ups if ups.use_unified_strength else brush, 'strength', text=tr('Сила', 'Strength'),
                     slider=True)
        if ob:
            lay.prop(ob, 'use_mesh_mirror_x', text=tr('Симметрия (левая = правая)', 'Symmetry (left = right)'))
        row = big(lay, 1.2)
        row.operator('ed.undo', text=tr('Отменить', 'Undo'), icon='LOOP_BACK')
        row.operator('ed.redo', text=tr('Повторить', 'Redo'), icon='LOOP_FORWARDS')
        big(lay, 1.5).operator('refit.sculpt_done', text=tr('ГОТОВО', 'DONE'), icon='CHECKMARK', depress=True)
        hint = lay.box()
        hint.label(text=tr('Колёсико - приблизить', 'Wheel - zoom'), icon='MOUSE_MMB')
        hint.label(text=tr('Средняя кнопка - вращать', 'Middle button - rotate'))
        hint.label(text=tr('F - размер кисти, Shift+F - сила', 'F - brush size, Shift+F - strength'))

    def draw_export(self, lay, context):
        draw_export(lay, context)


classes = (REFIT_OT_add_mod, REFIT_OT_remove_mod, REFIT_OT_choose_mod, REFIT_OT_choose_mesh, REFIT_OT_autofit,
           REFIT_OT_reset, REFIT_OT_sculpt, REFIT_OT_brush, REFIT_OT_sculpt_done,
           REFIT_OT_check, REFIT_OT_export_zip, REFIT_OT_export_vortex, REFIT_OT_export_mesh,
           REFIT_OT_export_menu, REFIT_OT_save, REFIT_OT_open,
           REFIT_PT_panel)


def logged(cls):
    """Любая ошибка кнопки пишется в log.txt и показывается в панели, а не теряется."""
    inner = cls.execute

    def execute(self, context):
        try:
            res = inner(self, context)
            C.log(f'{cls.bl_idname}: {res} | {context.scene.refit_status}')
            return res
        except UserError as e:
            report(self, str(e), 'WARNING')
            return {'CANCELLED'}
        except Exception as e:
            C.log(f'{cls.bl_idname} ERROR:\n{traceback.format_exc()}')
            report(self, tr('Ошибка: ', 'Error: ') + str(e).strip().splitlines()[-1][:250] +
                   tr(' (подробности в log.txt)', ' (details in log.txt)'), 'ERROR')
            return {'CANCELLED'}
    cls.execute = execute
    return cls


def register():
    S = bpy.types.Scene
    S.refit_mod = bpy.props.StringProperty()
    S.refit_mesh = bpy.props.StringProperty()
    S.refit_status = bpy.props.StringProperty()
    S.refit_body = bpy.props.StringProperty()
    S.refit_tattoo = bpy.props.EnumProperty(
        name=tr('Татуировка', 'Tattoo'), items=tattoo_items, update=on_tattoo,
        description=tr('Какая татуировка тела у твоего персонажа. Одежда не будет уходить под её оболочку',
                       "Which body tattoo your character wears. Clothing will not sink under its shell"))
    S.refit_scope = bpy.props.EnumProperty(
        name=tr('Что экспортировать', 'What to export'), default='ITEM',
        items=[('ITEM', tr('Вещь', 'Item'), tr('Только загруженная вещь с твоими правками',
                                              'Only the loaded item with your edits')),
               ('MOD', tr('Весь мод', 'Whole mod'), tr('Авто-подгонка всех вещей мода под обычное тело (★), один zip',
                                                      'Auto fit of all vanilla-body items (★) of the mod, one zip')),
               ('TATTOO', tr('Татуировки', 'Tattoos'), tr('Рефит 5 татуировок тела из игры под выбранное тело',
                                                         'Refit of the 5 game body tattoos for the chosen body'))])
    S.refit_tab = bpy.props.EnumProperty(
        name=tr('Вкладка', 'Tab'), default='FIT', update=on_tab,
        items=[('FIT', tr('Подгонка', 'Fit'), tr('Выбор вещи и авто-подгонка', 'Choose an item and auto fit')),
               ('SCULPT', tr('Лепка', 'Sculpt'), tr('Ручная правка кистями', 'Touch up with brushes')),
               ('EXPORT', tr('Экспорт', 'Export'), tr('В Vortex, в zip или для мододелов',
                                                     'To Vortex, to a zip or for modders'))])
    S.refit_all_mods = bpy.props.BoolProperty(
        name=tr('Показать все моды', 'Show all mods'), default=False,
        description=tr('Выкл: в списке только моды с одеждой. Вкл: все моды (если нужный мод не нашёлся)',
                       'Off: only mods with clothing are listed. On: all mods (if the one you need is missing)'))
    S.refit_modder_open = bpy.props.BoolProperty(default=False)
    S.refit_mesh_name = bpy.props.StringProperty(
        name=tr('Имя файла', 'File name'),
        description=tr('Имя .mesh без расширения. Предложено по твоему телу, можно поменять',
                       'Name of the .mesh without extension. Suggested from your body, you can change it'))
    S.refit_anchor = bpy.props.BoolProperty(
        name=tr('Привязка к телу', 'Snap to body'), default=True,
        description=tr('Вкл: авто-подгонка всегда сажает вещь на её место (ручные сдвиги сбрасываются). '
                       'Выкл: твои сдвиги сохраняются, вещь подгоняется там, куда ты её перетащил',
                       'On: auto fit always puts the item back in its place (manual moves are reset). '
                       'Off: your moves are kept and the item is fitted where you dragged it'))
    os.makedirs(C.WORK, exist_ok=True)
    for c in classes:
        if hasattr(c, 'execute'):
            logged(c)
        bpy.utils.register_class(c)
    bpy.app.handlers.load_post.append(restore_state)


def start():
    start_clothing_scan()  # пока строится сцена, в фоне ищем моды с одеждой
    if not bpy.app.background:
        # focus_view здесь не вызываем: переключение экрана из таймера иногда роняет Blender.
        # Режим «только 3D-вид» сохранён в самом studio.blend (tests/make_studio_blend.py).
        for step in (apply_theme, install_header):
            try:
                step()
            except Exception:
                C.log(f'{step.__name__}:\n' + traceback.format_exc())
        bpy.app.timers.register(window_title, first_interval=0.5)
    try:
        setup_scene()
        bpy.context.scene.refit_status = tr(f'Тело: {body_label()}. Выбери мод одежды, потом вещь со звёздочкой ★.',
                                            f'Body: {body_label()}. Choose a clothing mod, then an item marked ★.')
    except Exception as e:
        C.log('workshop start:\n' + traceback.format_exc())
        bpy.context.scene.refit_status = tr('Ошибка запуска: ', 'Start error: ') + str(e)[:200]
    return None


register()
# сцену строим, когда окно Blender готово (иначе нет экрана для настройки вида)
bpy.app.timers.register(start, first_interval=0.1)


def focus_tab(tries=[0]):
    # Вкладку боковой панели можно переключить только после её первой отрисовки - пробуем несколько раз
    tries[0] += 1
    done = False
    for w in bpy.context.window_manager.windows:
        for area in w.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'UI':
                    try:
                        region.active_panel_category = TAB
                        done = region.active_panel_category == TAB
                        area.tag_redraw()
                    except Exception:
                        pass
    return None if done or tries[0] > 10 else 0.5


bpy.app.timers.register(focus_tab, first_interval=0.8)
