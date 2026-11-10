// Coral corner clips: four snap-on pieces that wrap the vertical corners of the closed case
// (base + lid) and carry coral that coralgen grows from the post on each corner.
//
// A clip is the corner region minus the case envelope (plus play), so its inner faces follow the
// case and it keeps two hooks: one in the bed chamfer under the base, one in the top chamfer of the
// lid. Neither reaches past the case's bottom or top plane, so the case still sits flat and the
// C-Rail is untouched. The arms stop short of every port, button and LED. The clip snaps on by
// flexing over the chamfers (hook_depth sets the grip; PLA strain stays near 1.5 % at 0.5 mm).
// Clips print as worn: bottom on the bed, the hook in the lid chamfer leans 37 deg from vertical.
//
// Frame: base print frame (case bottom base_bot at z = 0), board frame in XY.
// Parts (-D 'part="..."'):
//   clips    - all four clips (coralgen host; print each body separately)
//   keepout  - not a part: case envelope (and the space above it) plus port and FPC corridors
//   assembly - clips on the closed case
include <../case/case.scad>

clip_t        = 2.4;      // clip wall thickness outside the case
clip_play     = 0.15;     // gap between clip and case faces
arm_len       = 9;        // arm length along each face, measured from the case corner
hook_depth    = 0.5;      // how far each hook reaches into its chamfer (horizontal)
post_size     = 9;        // corner post outside the case that carries the coral (>= 2 * coralgen radius.max)
corner_gap    = 0.6;      // clearance used for the coral keep-out around the case

hx = outer[0] / 2;
hy = outer[1] / 2;
case_z = [base_bot, lid_top];
case_h = lid_top - base_bot;

// Case outer envelope (base + lid, chamfers at both ends), grown by d
module case_envelope(d) {
    hull() {
        translate([0, 0, base_bot - d]) linear_extrude(0.01) offset(delta = d - bed_c[0]) oct2d(outer, edge_c);
        translate([0, 0, base_bot + bed_c[1]]) linear_extrude(case_h - 2 * bed_c[1]) offset(delta = d) oct2d(outer, edge_c);
        translate([0, 0, lid_top + d - 0.01]) linear_extrude(0.01) offset(delta = d - bed_c[0]) oct2d(outer, edge_c);
    }
}

module clip(sx, sy) {
    color("#2B2D2F") difference() {
        union() {
            // L-shell: both arms
            translate([sx > 0 ? hx - arm_len : -hx - clip_t, sy > 0 ? hy - arm_len : -hy - clip_t, base_bot])
                cube([arm_len + clip_t, arm_len + clip_t, case_h]);
            // Corner post diagonally outside the corner, solid over its whole top for coral roots
            translate([sx > 0 ? hx : -hx - post_size, sy > 0 ? hy : -hy - post_size, base_bot])
                cube([post_size, post_size, case_h]);
        }
        // The case plus play; what is left in the top and bottom chamfers are the hooks, cut back
        // to hook_depth from the case faces
        case_envelope(clip_play);
        translate([0, 0, base_bot - 1]) linear_extrude(case_h + 2) offset(delta = -hook_depth) oct2d(outer, edge_c);
    }
}

module clips() { for (sx = [-1, 1], sy = [-1, 1]) clip(sx, sy); }

module clips_keepout() {
    // The case and everything above it (lid windows, vents, bolts, label stay reachable)
    translate([0, 0, base_bot - ko_wall_bite]) linear_extrude(ko_tall) offset(delta = corner_gap) oct2d(outer, edge_c);
    // Front: USB-A + Qwiic, user button, LEDs, reset button, USB-C (whole front between the arms)
    translate([-hx + arm_len, -hy - ko_front_d, base_bot - 1]) cube([outer[0] - 2 * arm_len, ko_front_d, ko_tall]);
    // Left: microSD; right: battery + I2S (as base_keepout)
    translate([-hx - ko_side_d, sd_y[0] - 1.2 - 2.0 - ko_side_m, base_bot - 1])
        cube([ko_side_d, sd_y[1] - sd_y[0] + 2 * (1.2 + 2.0 + ko_side_m), ko_tall]);
    translate([hx, batt_y[0] - 0.6 - ko_side_m, base_bot - 1])
        cube([ko_side_d, i2s_y[1] - batt_y[0] + 2 * (0.6 + ko_side_m), ko_tall]);
    // Rear: FPC clamp block, clamp screws and camera FPC
    translate([fpc_cx - clamp_size[0] / 2 - ko_rear_m, hy - ko_wall_bite, base_bot - 1])
        cube([clamp_size[0] + 2 * ko_rear_m, clamp_y0 + clamp_gap + clamp_size[1] + ko_rear_d - hy + ko_wall_bite, ko_tall]);
}

module print_place() { translate([0, 0, -base_bot]) children(); }

part = "assembly";
if (part == "clips") print_place() clips();
else if (part == "keepout") print_place() clips_keepout();
else if (part == "assembly") { clips(); case_base(); case_lid(); case_fpc_clamp(); }
