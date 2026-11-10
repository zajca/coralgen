// Reef stand: desk stand for the CoralWatch case with a C-Rail receiver; coralgen grows coral from
// its plateau around the case.
//
// Stand frame: bed at z = 0, case board frame shifted up so the case bottom (base_bot) sits on the
// plateau at z = stand_h. The case drops in from above: two guide ridges sit in the C-Rail channels
// beside the rail (X) and a key sits in the rail's latch groove (Y); it lifts straight off. A slide-in
// dovetail is not possible here: the FPC clamp block closes the +X channel at the case rear, so the
// case could only enter from behind, and its slide path would take the rear plateau from the coral.
// The stand prints as modelled (bottom on the bed); ridge and key flanks are vertical.
//
// Parts (-D 'part="..."'):
//   stand    - printable stand (coralgen host)
//   keepout  - not a part: volume the coral must avoid (case and lid lift path, port, cable and
//              FPC corridors), stand frame
//   assembly - stand with the case, for renders
include <../case/case.scad>

// ---------- Stand ----------
stand_h       = 12;       // plateau height = case bottom height
side_m        = 24;       // plateau beyond the case outer walls, left and right
rear_m        = 30;       // plateau beyond the case rear wall (clamp block + FPC corridor + coral)
front_m       = 0;        // plateau front is flush with the case front face; cables hang in front
top_c         = 3;        // 45 deg chamfer around the plateau top edge
foot_cb       = [1.2, 1.6];   // bed chamfer [h, v], 37 deg from vertical as on the case
corner_c      = 6;        // vertical corner chamfer

// ---------- C-Rail locator (from the case rail: case.scad rail_*, jaw_x, latch_*) ----------
rx_gap        = 0.25;     // play between the rail face edge and a guide ridge
ridge_out_gap = 0.5;      // guide ridge outer face to the channel outer wall (case jaw_x)
ridge_top_gap = 0.5;      // guide ridge top to the channel ceiling
rear_stop_gap = 0.5;      // ridge rear end to the clamp block that closes the +X channel
lead_c        = 0.6;      // lead-in chamfer on ridge and key tops
key_gap       = 0.3;      // key play in the latch groove, per side and on top
key_edge      = 1.5;      // key ends stop this far inside the rail face edges

// ---------- Cable notch for a down-angled USB-C plug (case usbc_head_*) ----------
notch_gap     = 0.5;

// ---------- Coral keep-out ----------
lift_gap      = 1.0;      // free play around the case as it is lifted off

// Derived
sz            = stand_h - base_bot;                     // case frame -> stand frame z shift
hx            = outer[0] / 2;
hy            = outer[1] / 2;
case_h        = lid_top - base_bot;
plat_x        = [-hx - side_m, hx + side_m];
plat_y        = [-hy - front_m, hy + rear_m];
clamp_y_start = hy - 2;                                 // clamp block front face (case.scad clamp_block)
ridge_y       = [plat_y[0] + top_c, clamp_y_start - rear_stop_gap];   // starts behind the top chamfer
ridge_x       = [rail_w / 2 + rx_gap, jaw_x - ridge_out_gap];        // rail is widest at its face
ridge_h       = rail_h - ridge_top_gap;
clamp_y_end   = clamp_y0 + clamp_gap + clamp_size[1];                 // rear end of the FPC clamp bar

module case_place() { translate([0, 0, sz]) children(); }

module plateau() {
    size = [plat_x[1] - plat_x[0], plat_y[1] - plat_y[0]];
    translate([(plat_x[0] + plat_x[1]) / 2, (plat_y[0] + plat_y[1]) / 2, 0])
        cprism(size, 0, stand_h, corner_c, foot_cb, [top_c, top_c]);
}

// Box with a lead-in chamfer on its top edges
module lead_box(p0, p1) {
    hull() {
        translate(p0) cube([p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2] - lead_c]);
        translate(p0 + [lead_c, lead_c, 0]) cube([p1[0] - p0[0] - 2 * lead_c, p1[1] - p0[1] - 2 * lead_c, p1[2] - p0[2]]);
    }
}

module guide_ridges() {
    for (s = [0, 1]) mirror([s, 0, 0])
        lead_box([ridge_x[0], ridge_y[0], stand_h - 0.01], [ridge_x[1], ridge_y[1], stand_h + ridge_h]);
}

module latch_key() {
    kx = rail_w / 2 - key_edge;
    lead_box([-kx, latch_y - latch_w / 2 + key_gap, stand_h - 0.01], [kx, latch_y + latch_w / 2 - key_gap, stand_h + latch_d - key_gap]);
}

module cable_notch() {
    translate([usbc_head_x[0] - notch_gap, plat_y[0] - 1, -1])
        cube([usbc_head_x[1] - usbc_head_x[0] + 2 * notch_gap, 1 + usbc_head_depth + notch_gap, stand_h + 2]);
}

module reef_stand() {
    color(c_black) difference() {
        union() {
            plateau();
            guide_ridges();
            latch_key();
        }
        cable_notch();
    }
}

module stand_keepout() {
    // Lift-off path of the whole case: outer footprint plus the FPC clamp bar at the rear
    translate([-hx - lift_gap, plat_y[0] - lift_gap, stand_h - ko_wall_bite])
        cube([outer[0] + 2 * lift_gap, clamp_y_end + lift_gap - plat_y[0] + lift_gap, ko_tall]);
    // Port, cable and FPC corridors (case keep-out, shifted onto the plateau)
    case_place() base_keepout();
    cable_notch();
}

part = "assembly";
if (part == "stand") reef_stand();
else if (part == "keepout") stand_keepout();
else if (part == "assembly") {
    reef_stand();
    case_place() { case_base(); case_lid(); case_fpc_clamp(); }
}
