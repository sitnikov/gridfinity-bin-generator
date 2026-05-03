# Gridfinity Web Generator — для Claude

Веб-генератор Gridfinity-бункеров. Python-порт `UltraLightGridfinityBins.scad`
(HuMa\_Meng) → Flask + Three.js. CSG-движок — **manifold3d** (mesh-CSG в C++).

## Запуск

Python 3.10–3.12. На 3.14 OCP-бэкенд не собирается:

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python app.py     # http://127.0.0.1:5050/
```

Все скрипты ожидают `cwd = корень репо` (импорт `gridfinity` относительно).

## Архитектура

| Файл                     | Роль                                                   |
|--------------------------|--------------------------------------------------------|
| `gridfinity.py`          | CAD-движок на manifold3d (1:1 порт SCAD)               |
| `gridfinity_b123.py`     | Старый build123d-бэкенд — точный CAD-референс          |
| `app.py`                 | Flask: GET `/`, POST `/generate`, LRU-кэш STL          |
| `templates/index.html`   | Форма + Three.js viewer                                |
| `compare_geometry.py`    | Регресс: bbox/volume manifold vs build123d             |
| `verify_spec.py`         | Сверка с официальной Gridfinity spec                   |
| `verify_reference.py`    | Stackability против reference STL (Printables 265271)  |
| `gridfinity_specification.pdf` | Локальная копия spec (grizzie17)                 |
| `UltraLightGridfinityBins.scad` | Оригинальный SCAD — источник истины             |

## Ключевые design decisions

### Backend: manifold3d, не build123d

Изначально начинали с build123d (NURBS / OpenCascade) — он давал ~0.8–4 с
на бункер из-за дорогих boolean ops. Переписали на manifold3d (mesh-CSG) —
сейчас 30–200 мс, в ~20× быстрее.  build123d сохранён в `gridfinity_b123.py`
исключительно как референс для регресс-теста — **не используется в проде**.

### SCAD → manifold3d mapping

Каждая SCAD-конструкция переведена дословно. **Не упрощать и не оптимизировать
геометрию** — мы повторяем исходник `UltraLightGridfinityBins.scad` 1:1:

| SCAD                    | manifold3d                              |
|-------------------------|-----------------------------------------|
| `cube`, `cylinder`      | `Manifold.cube`, `Manifold.cylinder`    |
| `translate`, `mirror`   | `.translate()`, `.mirror()`             |
| `union` / `difference`  | `+` / `-`                               |
| `hull() { 4 cylinders }`| `Manifold.batch_hull([…])`              |

Если кто-то добавляет фичу — ищи в SCAD-исходнике как там это сделано, и
переноси в том же стиле. Не лофти и не упрощай — convex hull 4-х цилиндров
это **ровно та же геометрия**, что в SCAD CGAL.

### CSG robustness: EPS_VOID

manifold3d (как и любой mesh-CSG) роняется на **coplanar surfaces** —
если void в `_diff_all` имеет грань точно совпадающую с outer surface,
от subtract остаётся zero-thickness shell, и следующие subtract ломаются.

Решено через `_hull4_void()`: void растёт на `EPS_VOID = 1e-3` мм во всех
направлениях. Это ниже точности 3D-печати в 100×, но устраняет
robustness-проблемы CGAL/manifold.

Применяется **только в `_make_bin_stacklip`**, где void и outer имеют
совпадающие радиусы. Если добавляешь новый difference и видишь странные
артефакты по верху — проверь, нет ли coplanar surfaces, замени `_hull4`
на `_hull4_void` для voids.

### Дискретизация цилиндров

Адаптивная, как в OpenSCAD: `FA = 8°`, `FS = 0.25 мм` (значения из секции
`[Hidden]` исходного SCAD).  Каждый цилиндр получает
`segments = max(5, min(⌈360/FA⌉, ⌈2π·r/FS⌉))` через `_segments_for_radius()`.

Это даёт точно ту же триангуляцию, что и OpenSCAD сам — на 3×3×6 со всеми
features наш volume отличается от OpenSCAD-рендера на **0.0025 %** (≈3 мм³),
bbox X/Y совпадает ровно. Маленькие радиусы получают мало сегментов
(например r=0.6 → 16), большие — больше (r=8 → 45).

`CIRCULAR_SEGMENTS = 32` оставлен как fallback, но фактически нигде не
используется — все вызовы `_cyl()` идут через адаптивный счётчик.

### Magnet position отклоняется от spec

HuMa\_Meng's SCAD ставит магниты в `(BASIC_RADIUS_2, BASIC_RADIUS_2) = (8, 8)`
от угла grid unit, а Gridfinity spec говорит 4.8 мм от наружной грани (=5.05
от угла unit с offset).  Это **специальное отклонение исходного SCAD**,
не баг. Описано в README. Если кто-то жалуется — менять только если
пользователь явно попросит, иначе нарушим 1:1-соответствие исходнику.

### Серверный кэш STL

LRU 32 элемента + per-key Lock. Ключ = sorted tuple of `asdict(params)`.
Повторные запросы (debounce-флаппинг, return к прежнему значению) — <1 мс.

## Тесты

Все три скрипта запускаются из корня репо без аргументов, выходят с кодом
ненулевой если что-то расходится:

```bash
./venv/bin/python verify_spec.py        # 24/24 точек spec
./venv/bin/python verify_reference.py   # vs Printables 265271
./venv/bin/python compare_geometry.py   # vs build123d (нужен build123d)
```

Перед коммитом изменений геометрии **обязательно прогоняй `verify_spec.py`** —
это база. `compare_geometry.py` опциональный, требует тяжёлый build123d.

## Грабли / gotchas

* **Не использовать Python 3.13/3.14** — у `cadquery-ocp` нет колёс, build123d
  не установится. 3.12 — sweet spot.
* **Не запускать тесты без `cd <repo>`** — модули импортируются
  относительно cwd.
* **Reference STL в `gridfinity-lite-...-model_files/` — это ASCII-STL.**
  Бинарный reader на них рухнет. `verify_reference.py` поддерживает оба
  формата, не сломай при правке.
* **`_diff_all`/`_union_all` фильтруют empty parts** через `is_empty()`. Если
  модуль может вернуть пустой `Manifold()`, это нормально — фильтрация
  отработает.
* **0.75 мм у самого верха лип** — это `h5` в SCAD-коде, intentional cut.
  Spec даёт 24.69 мм для 1×1×3 (R0.5 fillet), reference STL — 24.80,
  наш — 24.65. Все в пределах 0.15 мм, не повод править.
* **Half-grid (`grids_x = 1.5`)**: в SCAD это специальный режим с mirror,
  смотри `_mirror_xy()`. Если меняешь base/clean — обязательно прогоняй
  `verify_spec.py` с half-grid пресетами (там уже есть).

## Конвенции

* **Не добавляй фичи, которых нет в SCAD-исходнике** без явной просьбы
  пользователя. Этот проект — порт, а не fork.
* **Координаты в `_make_*` функциях — в "локальных" единицах модуля** (где
  start_x/start_y = угол grid unit или footprint). Перевод в финальный фрейм
  делается в `build_bin()` через `_mirror_xy()` и финальный
  `translate([-Wx/2, -Wy/2, 0])`.
* **Все размеры в мм**.  EPS — `1e-3` мм (= 1 µm), tolerance проверок —
  `0.001` для CSG-eps, `0.05` для геометрических допусков, `0.5` для
  stackability.
* **Не вытаскивать build123d в `requirements.txt`** — он тяжёлый (200 МБ
  OCP), нужен только для `compare_geometry.py`. Кто хочет — поставит сам.
