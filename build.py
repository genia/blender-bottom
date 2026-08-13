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
body_z   = 0.0
body_len = 39.0

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
    ("Outer Rim",      57.0, 48.0, 39, 20.0),
    ("Inner Ring",     48.0, 41.5, 16.0,  1.0),
    ("Inner Shoulder", 48.0, 36.5, 13.0,  3.0),   # solid (inner=0 = no hole)
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

# 9 ribs, starting at 0°, incrementing by 40°, constant radius 48
rib_angles = [i * 40 for i in range(9)]
rib_radius = 47.0

# Cutter: main body outer surface — trim ribs flush
body_outer = Part.makeCylinder(51, 63,
                                Base.Vector(0, 0, 0),
                                Base.Vector(0, 0, 1))

for i, angle in enumerate(rib_angles):
    rad = math.radians(angle)
    cx = rib_radius * math.cos(rad)
    cy = rib_radius * math.sin(rad)
    cyl = Part.makeCylinder(6.0, 39.0, Base.Vector(cx, cy, 0), Base.Vector(0, 0, 1))
    cyl = cyl.cut(body_outer)  # keep only portion outside main body
    add_part(cyl, f"🔩 External Rib {i+1}  (r=6mm @ {angle}°)")
    print(f"  Rib {i+1}: {angle}° → ({cx:.0f}, {cy:.0f})")

# ═══════════════════════════════════════════════════════
#  RECTANGULAR TABS  (3, projecting outward from main body)
# ═══════════════════════════════════════════════════════

print("\n─── Rectangular Tabs ───")

bottom_tab_angle = 60.0
tab_rel_angles = [-40, 80, 200]
tab_abs_angles = [bottom_tab_angle + a for a in tab_rel_angles]
main_outer_r = 51.0
tab_proj = 1.0     # projection outside main body
tab_h = 3.0        # height
tab_w = 8.0        # width
tab_z_bottom = 32.0

for i, angle in enumerate(tab_abs_angles):
    rad = math.radians(angle)
    mid_r = main_outer_r + tab_proj / 2.0   # 53
    z_mid = tab_z_bottom + tab_h / 2.0       # 33.5
    center = Base.Vector(mid_r * math.cos(rad), mid_r * math.sin(rad), z_mid)
    
    # Box extends inward so cut at r=51 leaves a curved inner face
    box = Part.makeBox(tab_proj + 4, tab_w, tab_h)   # X=radial (extra 4 inward)
    rot = App.Rotation(Base.Vector(0, 0, 1), angle)
    local_center = Base.Vector((tab_proj + 4)/2, tab_w/2, tab_h/2)
    pos = center - rot.multVec(local_center)
    box.Placement = Base.Placement(pos, rot)
    
    # Cut with main body cylinder (r=51) so near corners sit exactly at r=51
    tab = box.cut(body_outer)
    add_part(tab, f"▭ Rectangular Tab {i+1}  @ {angle}°")
    print(f"  Tab {i+1}: {angle}° (r={main_outer_r}..{main_outer_r+tab_proj}, Z={tab_z_bottom}..{tab_z_bottom+tab_h})")

# ═══════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════
#  BOTTOM TAB  (at 60°, extracted from planar face cluster)
# ═══════════════════════════════════════════════════════
#  BOTTOM TAB  — built from explicit vertex constants
#  Faces correspond to original STEP faces 35,36,37,41,43,44,45,46,49,50
# ═══════════════════════════════════════════════════════

print("\n─── Bottom Tab ───")

# Vertex data extracted from original STEP (X, Y, Z in mm)
# Face 35 (Plane, area=67.85) — side wall, outer edge extended +2mm to r=49.5
f35 = [
    (25.3122, 29.842, 8.0),
    (30.7973, 38.7528, 8.0),
    (30.7973, 38.7528, 15.0),
    (25.3122, 29.842, 15.0),
]
# Face 36 — bottom face, outer edge extended +2mm to r=49.5
f36 = [
    (13.1878, 36.842, 8.0),
    (18.1624, 46.0475, 8.0),
    (30.7973, 38.7528, 8.0),
    (25.3122, 29.842, 8.0),
]
# Face 37 (Plane, area=67.85) — side wall, outer edge extended +2mm to r=49.5
f37 = [
    (13.1878, 36.842, 8.0),
    (18.1624, 46.0475, 8.0),
    (18.1624, 46.0475, 15.0),
    (13.1878, 36.842, 15.0),
]
# Face 41 (Plane, area=112.00) — side wall
f41 = [
    (25.3122, 29.842, 8.0),
    (13.1878, 36.842, 8.0),
    (13.1878, 36.842, 15.0),
    (25.3122, 29.842, 15.0),
]
# Face 43 (Plane, area=49.50) — inner chamfer key side
f43 = [
    (24.3971, 33.257, 3.0),
    (24.3971, 33.257, 8.0),
    (16.6029, 37.757, 8.0),
    (16.6029, 37.757, 0.0),
    (21.799, 34.757, 0.0),
]
# Face 44 (Plane, area=12.00)
f44 = [
    (17.6029, 39.4891, 0.0),
    (17.6029, 39.4891, 8.0),
    (16.6029, 37.757, 8.0),
    (16.6029, 37.757, 0.0),
]
# Face 45 — outer side with chamfer notch, full height Z=0..14
f45 = [
    (22.799, 36.4891, 0.0),
    (25.3971, 34.9891, 3.0),
    (25.3971, 34.9891, 8.0),
    (17.6029, 39.4891, 8.0),
    (17.6029, 39.4891, 0.0),
]
# Face 46 (Plane, area=8.00)
f46 = [
    (25.3971, 34.9891, 3.0),
    (25.3971, 34.9891, 8.0),
    (24.3971, 33.257, 8.0),
    (24.3971, 33.257, 3.0),
]
# Face 49 (Plane, area=12.00)
f49 = [
    (21.799, 34.757, 0.0),
    (16.6029, 37.757, 0.0),
    (17.6029, 39.4891, 0.0),
    (22.799, 36.4891, 0.0),
]
# Face 50 (Plane, area=8.49)
f50 = [
    (24.3971, 33.257, 3.0),
    (21.799, 34.757, 0.0),
    (22.799, 36.4891, 0.0),
    (25.3971, 34.9891, 3.0),
]

# Upper part: extrude f36 up 7mm, then cut with bore cylinder (r=48)
f36_pts = [Base.Vector(x, y, z) for x, y, z in f36]
f36_face = Part.Face(Part.Plane(f36_pts[0], f36_pts[1], f36_pts[2]),
                     Part.makePolygon(f36_pts + [f36_pts[0]]))
upper_solid = f36_face.extrude(Base.Vector(0, 0, 7))   # Z=8..15
bore_cyl = Part.makeCylinder(48, 63, Base.Vector(0, 0, 0), Base.Vector(0, 0, 1))
upper_solid = upper_solid.common(bore_cyl)

# Lower chamfer faces (f43..f50)
lower_faces = []
for verts in [f43, f44, f45, f46, f49, f50]:
    pts = [Base.Vector(x, y, z) for x, y, z in verts]
    poly = Part.makePolygon(pts + [pts[0]])
    plane = Part.Plane(pts[0], pts[1], pts[2])
    lower_faces.append(Part.Face(plane, poly))

compound = Part.Compound([upper_solid] + lower_faces)
add_part(compound, "Bottom Tab")
print(f"  Upper solid cut at r=48 + {len(lower_faces)} chamfer faces")

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
