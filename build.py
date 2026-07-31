"""
build.py — Parse the original STEP into a structured FreeCAD FCStd tree.
Output: model.FCStd
Backups in backups/ — saved before each modification.
"""
import os, math
from collections import defaultdict
import Import, Part
from Part import BRepOffsetAPI
from FreeCAD import Base

# ── Paths ──────────────────────────────────────────────
HERE = os.path.dirname(__file__)
SRC  = os.path.join(HERE, "3_d_print_model.main_design (1).step")
OUT  = os.path.join(HERE, "model.FCStd")

# ── Document setup ─────────────────────────────────────
doc = App.newDocument("Model")
Import.insert(SRC, doc.Name)

# Hide the raw import — it's our reference only
ref = doc.Objects[0]
ref.Visibility = False
ref.Label = "🔒 Original STEP (reference)"

def add_part(shape, label):
    """Add a Part::Feature to the document with a descriptive label."""
    obj = doc.addObject("Part::Feature", label.replace(" ", "_"))
    obj.Label = label
    obj.Shape = shape
    return obj

# ═══════════════════════════════════════════════════════
#  MAIN BODY — hollow tube with internal thread cut
# ═══════════════════════════════════════════════════════

print("─── Main Body (hollow, with internal thread) ───")

bore_r   = 48.0    # inner diameter = 96mm
wall     = 3.0     # wall thickness
outer_r  = bore_r + wall   # 51mm
pitch    = 6.0
angle    = 60.0
fillet_r = 0.5
depth    = 3.0     # thread depth inward from bore
z_start  = 27.5    # top of thread at Z=48, minus 1 turn removed from bottom
z_len    = 20.5    # threaded portion height
body_z   = -2.0
body_len = 40.0

# Build: solid cylinder → cut (bore + thread grooves) = threaded tube
solid_cyl = Part.makeCylinder(outer_r, body_len,
                               Base.Vector(0, 0, body_z),
                               Base.Vector(0, 0, 1))
bore_cyl  = Part.makeCylinder(bore_r, body_len,
                               Base.Vector(0, 0, body_z),
                               Base.Vector(0, 0, 1))

# Thread teeth: profile in XZ plane (perpendicular to helix)
# X = radial inward (-X toward center), Z = circumferential
ha = math.radians(angle / 2)
hw = depth * math.tan(ha)

# Fillet geometry:
#   Arc center on bisector (-X), offset from tip by r/sin(ha)
ac = -depth + fillet_r / math.sin(ha)
#   Tangent points: projection of arc center onto each side line
#   Side: from base (0,±hw) to tip (-depth,0); dir = (-depth, ±hw)
side_len2 = depth*depth + hw*hw
t = (-ac * depth + hw*hw) / side_len2
tx = -depth * t                        # tangent X (negative)
tz = hw * (1 - t)                     # tangent Z (absolute)

p_bl = Base.Vector(  0, 0, -hw)
p_tl = Base.Vector( tx, 0, -tz)
p_tr = Base.Vector( tx, 0,  tz)
p_br = Base.Vector(  0, 0,  hw)

arc_mid = Base.Vector(ac - fillet_r, 0, 0)
arc = Part.Arc(p_tl, arc_mid, p_tr)
tooth_profile = Part.Wire([
    Part.LineSegment(p_bl, p_tl).toShape(),
    arc.toShape(),
    Part.LineSegment(p_tr, p_br).toShape(),
    Part.LineSegment(p_br, p_bl).toShape(),
])

helix = Part.makeHelix(pitch, z_len, bore_r, 0, False)
helix.translate(Base.Vector(0, 0, z_start))

# Profile must be at path start in world coords
start_pt = helix.Edges[0].valueAt(helix.Edges[0].FirstParameter)
tooth_profile.translate(start_pt)

sweep = BRepOffsetAPI.MakePipeShell(helix)
sweep.setFrenetMode(True)
sweep.add(tooth_profile, False, False)
sweep.build()
sweep.makeSolid()

if sweep.isReady():
    teeth = sweep.shape()
    # Tube and teeth as separate parts
    tube = solid_cyl.cut(bore_cyl)
    add_part(tube, f"Main Body  (ID={bore_r*2}mm, wall={wall}mm)")
    add_part(teeth, f"Thread Teeth  ({angle}°, {pitch}mm pitch, {depth}mm deep, R{fillet_r}mm)")
    print(f"  ✅ Thread teeth: {angle}° {pitch}mm pitch, {depth}mm deep, R{fillet_r}mm")
else:
    tube = solid_cyl.cut(bore_cyl)
    add_part(tube, f"Main Body  (ID={bore_r*2}mm, wall={wall}mm, no thread)")
    print(f"  ❌ Thread sweep failed")

# ═══════════════════════════════════════════════════════
#  OTHER CONCENTRIC CYLINDERS  — all hollow tubes
# ═══════════════════════════════════════════════════════

print("\n─── Other Cylinders (hollow tubes) ───")

# (name, outer_r, inner_r, z_start, length)
tubes = [
    ("Outer Rim",      57.0, 48.0, 40.0, 23.0),
    ("Inner Ring",     47.5, 41.5, 16.0,  1.0),
    ("Inner Shoulder", 47.5, 36.5, 13.0,  3.0),   # solid (inner=0 = no hole)
]

for name, outer_r, inner_r, z, length in tubes:
    outer = Part.makeCylinder(outer_r, length,
                               Base.Vector(0, 0, z),
                               Base.Vector(0, 0, 1))
    if inner_r > 0:
        inner = Part.makeCylinder(inner_r, length,
                                   Base.Vector(0, 0, z),
                                   Base.Vector(0, 0, 1))
        shape = outer.cut(inner)
        desc = f"(r={outer_r}mm tube, wall={outer_r-inner_r}mm)"
    else:
        shape = outer
        desc = f"(r={outer_r}mm solid)"
    
    add_part(shape, f"{name}  {desc}")
    print(f"  {name}: outer={outer_r}mm  inner={inner_r}mm  Z={z}→{z+length}mm")

# ═══════════════════════════════════════════════════════
#  EXTERNAL RIBS  (on the outer surface of Main Body)
# ═══════════════════════════════════════════════════════

print("\n─── External Ribs ───")

# Positions extracted from the original STEP surface centers
rib_positions = [
    (48.0,   0.0),
    (36.0,  30.5),
    (36.0, -30.5),
    ( 8.0,  47.0),
    ( 8.0, -47.0),
    (-24.0,  41.0),
    (-24.0, -41.0),
    (-45.0,  16.0),
    (-45.0, -16.0),
]

# Cutter: main body outer surface — trim ribs flush
body_outer = Part.makeCylinder(51, 63,
                                Base.Vector(0, 0, 0),
                                Base.Vector(0, 0, 1))

for i, (cx, cy) in enumerate(rib_positions):
    cyl = Part.makeCylinder(6.0, 40.0, Base.Vector(cx, cy, 0), Base.Vector(0, 0, 1))
    cyl = cyl.cut(body_outer)  # keep only portion outside main body
    add_part(cyl, f"🔩 External Rib {i+1}  (r=6mm @ {cx:.0f},{cy:.0f})")
    print(f"  Rib {i+1}: @ ({cx:.0f}, {cy:.0f})")

# ═══════════════════════════════════════════════════════
#  RADIAL RIBS  (extracted from planar face clusters)
# ═══════════════════════════════════════════════════════

print("\n─── Radial Ribs ───")

by_normal = defaultdict(list)
for f in ref.Shape.Faces:
    if type(f.Surface).__name__ != 'Plane':
        continue
    n = f.Surface.Axis
    if abs(n.z) > 0.99 or f.Area < 15:
        continue
    by_normal[(round(n.x, 2), round(n.y, 2), round(n.z, 2))].append(f)

rib_count = 0
for (nx, ny, nz), faces in sorted(by_normal.items(), key=lambda x: -len(x[1])):
    if len(faces) < 2:
        continue
    angle = round(math.degrees(math.atan2(ny, nx)))
    if angle != 60:  # keep only the 60° rib
        continue
    try:
        compound = Part.Compound(faces)
        extruded = compound.extrude(Base.Vector(nx * 2, ny * 2, 0))
        add_part(extruded, f"🏗️ Radial Rib @ {angle}°")
        rib_count += 1
    except:
        pass

print(f"  {rib_count} ribs extracted")

# ═══════════════════════════════════════════════════════
#  CHAMFERS
# ═══════════════════════════════════════════════════════

conical = [f for f in ref.Shape.Faces if 'Cone' in type(f.Surface).__name__]
if conical:
    add_part(Part.Compound(conical), "🔺 Chamfers")
    print(f"\n─── Chamfers ───\n  {len(conical)} conical faces")

# ═══════════════════════════════════════════════════════
#  SAVE
# ═══════════════════════════════════════════════════════

total = len([o for o in doc.Objects if not o.Label.startswith("🔒")])
doc.saveAs(OUT)
print(f"\n{'='*50}")
print(f"✅ {total} parts saved → {OUT}")
print(f"{'='*50}")
