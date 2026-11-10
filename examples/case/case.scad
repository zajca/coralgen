// CoralWatch pod: printable two-part case for the Synaptics Coralboard SL.
//
// Board frame (shared with concept/lib.scad): PCB outline centred on XY, PCB top at z = 0,
// front edge (USB-A, USB-C, RESET/USER) at -Y. All board positions below were measured from
// Synaptics_CoralBoard_SL.stl (connected-component bounding boxes and sections); values marked
// ASSUMPTION are not in the STL and come from the official board photo or typical part data.
//
// Parts and print orientation (select with -D 'part="..."'):
//   base   - black, prints as modelled: C-Rail and feet on the bed, open side up
//   lid    - orange, prints upside down: top face (debossed label) on the bed
//   clamp  - camera FPC clamp bar, prints upside down: flat top on the bed
//   base_cut     - not a part: every void of the base, cut away from coralgen roots anchored in the wall
//   base_keepout - not a part: volume (base print frame) that coralgen branches must avoid
// Every wall cut-out is a notch that opens at the base/lid parting plane, so neither shell
// needs supports (checked with scripts/check_overhangs.py).
//
// Hardware: 4x M3x16 socket head + 4x M3 hex nut (lid -> board -> base, clamps the PCB),
//           2x M3x12 socket head + 2x M3 hex nut (FPC clamp bar).

use <../coral_motif.scad>

// ---------- Board data (measured) ----------
board_stl     = "../../Synaptics_CoralBoard_SL.stl";
board_offset  = [-32.7, -26.975, 0];       // STL origin -> board frame
pcb_size      = [73, 58];
pcb_t         = 1.6;
pcb_holes     = [[-33, -22.5], [32, -22.5], [-33, 25.5], [32, 25.5]];   // 3.2 mm, M3

top_parts_max = 8.59;      // GPIO pins / mikroBUS sockets
bottom_min    = -3.78;     // stick-on rubber domes under the PCB (four, 7.9 mm)

// Front edge (-Y)
usb_a_c       = [-7.0, 3.84];               // receptacle centre (x, z), shell x -14.25..0.25, z 0.34..7.34
usb_c_c       = [23.07, 1.73];              // receptacle centre (x, z), shell x 18.6..27.54, z 0.15..3.31
qwiic_x       = [-20.85, -14.85];           // JST-SH 4-pin side entry, mouth at y -28.39, z 0..2.97
btn_user_x    = -26.0;                      // actuator x -27.3..-24.7, z 0.25..1.65, tip y -29.97
btn_reset_x   = 10.22;                      // actuator x 8.92..11.52
btn_tip_y     = -29.97;
led_x         = [[3.10, 5.88], [14.48, 15.38]];   // red+green pair, blue; z 0..0.9, y -27.8..-26.1
dsi_x         = [1.75, 18.25];              // DSI FPC socket on the underside, mouth faces -Y at y 3.4
usbc_head_x   = [16.5, 29.5];              // right-angle plug head footprint (cable down)
usbc_head_depth = 1.5;                      // recess into the front outer face for the plug head
// Right edge (+X)
batt_y        = [-17.12, -11.12];           // JST-PH 2-pin side entry, z 0..6.15, faces +X
i2s_y         = [-7.5, 1.5];                // JST-SH 7-pin side entry, z 0..2.97, faces +X
// Left edge (-X)
sd_y          = [-6.3, 5.4];                // microSD push-push socket mouth at x -34.17, card z 0.75..1.75
// Top side
csi_x         = [4.45, 20.95];              // CSI FPC socket, mouth faces +Y at y 20.65, z ~0.85
gpio_box      = [[-28.42, 22.96], [-3.02, 28.04]];
i3c_box       = [[-8.79, 7.49], [-3.21, 12.57]];      // 2x2 vertical socket labelled I3C on the photo
mikrobus_box  = [[0.38, 8.18], [25.73, 29.0]];        // both 1x8 sockets
boot_sw_box   = [[-12.9, -5.7], [-9.3, 0.7]];         // ASSUMPTION: S3 is not in the STL; from photo
som_box       = [[0.77, -21.2], [28.77, 6.8]];        // AstraSOM module (heat source)

// ---------- Case parameters ----------
gap           = 0.5;      // board edge to inner wall
wall          = 2.4;
inner         = [pcb_size[0] + 2 * gap, pcb_size[1] + 2 * gap];
outer         = [inner[0] + 2 * wall, inner[1] + 2 * wall];

split_z       = 0;        // base/lid parting plane (PCB top)
floor_top     = -4.6;     // 0.8 mm under the rubber domes
floor_t       = 2.0;
floor_bot     = floor_top - floor_t;
ceiling_z     = 9.2;      // 0.6 mm over the tallest top part
top_t         = 2.0;
lid_top       = ceiling_z + top_t;

edge_c        = 1.6;      // vertical edge chamfer
bed_c         = [1.2, 1.6];   // chamfer on bed-side outer edges: 37 deg from vertical, prints unsupported
seam_c        = 0.6;      // V-groove at the parting line
foot_c        = 0.4;      // first-layer chamfer on bed edges of internal features

lip_t         = 1.0;      // alignment lip under the lid rim
lip_h         = 1.2;
lip_gap       = 0.2;

// C-Rail (male dovetail under the floor, runs along Y)
rail_w        = 30;       // width at the rail face
rail_h        = 4;
rail_ang      = 15;       // flank angle from vertical
rail_flank    = rail_h * tan(rail_ang);
base_bot      = floor_bot - rail_h;
jaw_x         = 22.5;     // channel outer wall: 44 mm receiver + 0.5 mm clearance per side
latch_w       = 3;        // spring-latch groove across the rail face (front end)
latch_d       = 1.5;
latch_y       = -outer[1] / 2 + 5;

// Fasteners
m3_d          = 3.4;
m3_head_d     = 6.0;      // ISO 4762 M3 head 5.5 mm
m3_head_h     = 3.0;
nut_af        = 5.6;      // 5.5 mm nut, slight press fit so it stays in the pocket
nut_h         = 2.4;
bolt_len      = 16;       // lid -> base through bolts
seat_z        = lid_top - m3_head_h - 0.2;   // head sits 0.2 below the top face
standoff_d    = 5.4;      // 0.5 mm from the rubber domes next to the left holes
pillar_d      = 5.8;      // foot of the lid pillar on the PCB (z 0..pillar_neck_z)
pillar_top_d  = 7.0;      // upper pillar around the head counterbore, 0.5 mm from the M.2 socket
pillar_neck_z = 2.0;      // parts next to the holes are below 1.2 mm, so the pillar widens above this

// Flexure buttons cut into the lid front wall
tab_w         = 5.0;
tab_slot      = 0.6;
tab_t         = 0.9;      // ~4.7 N to press: 0.5 mm free play + 0.25 mm switch travel
tab_root_z    = 8.6;
tab_face_y    = btn_tip_y - 0.55;   // 0.55 mm free play absorbs lid/board position tolerance

// Ventilation over the SoM: vertical slots through the lid top
vent_w        = 1.6;
vent_pitch    = 3.4;
vent_n        = 8;
vent_y        = [-19.5, 4.5];

// Label
label_text    = "CORALWATCH";
label_font    = "Liberation Sans:style=Bold";
label_size    = 4.2;
label_depth   = 0.6;
label_pos     = [0, -26.3];

// Coral motif debossed on the lid's free left area (between the edge windows and the antenna pocket);
// the trunk points to the USB edge, so it stands upright when the case hangs as a backpack (USB down)
coral_base    = [-26, -12];
coral_h       = 20;          // coral_2d is about 1.13 x as wide as tall: 22.6 mm, x -37.3..-14.7 (window at -13)
coral_stroke  = 1.0;
coral_levels  = 3;
coral_seed    = 4;
coral_depth   = 0.6;

// Internal flat Wi-Fi antenna pocket in the lid ceiling (adhesive FPC antenna up to 40 x 10 mm)
ant_box       = [[-36.6, -18], [-26.6, 22]];
ant_depth     = 0.6;

// Camera FPC exit (rear wall) and clamp
fpc_w         = 16;          // the 15-pin camera end of a 22-to-15 cable is ~16 mm; the cable may keep that width
                             // up to the board, so the exit is sized for it like every slot in the robot
fpc_slot      = [fpc_w + 1.0, 2.4];          // width, height above the parting plane
fpc_cx        = (csi_x[0] + csi_x[1]) / 2;
clamp_size    = [34, 8, 3];
clamp_gap     = 0.3;                         // to the lid rear face
clamp_y0      = outer[1] / 2;
clamp_screw_dx = 12.5;                       // screw holes clear the 17 mm slot by 2.3 mm
clamp_screw_y = clamp_y0 + clamp_gap + clamp_size[1] / 2;
clamp_relief  = 0.05;                        // shallower than the FPC, so the bar grips it
clamp_screw_len = 12;

eps = 0.01;
$fn = 40;

c_black  = "#2B2D2F";
c_orange = "#FA6831";

// ---------- Primitives ----------
module oct2d(size, c) {
    offset(delta = c, chamfer = true) square([size[0] - 2 * c, size[1] - 2 * c], center = true);
}

// Convex prism with chamfered vertical edges and independent bottom/top edge chamfers [h, v]
module cprism(size, z0, z1, c_side, c_bot = [0, 0], c_top = [0, 0]) {
    hull() {
        translate([0, 0, z0]) linear_extrude(eps) offset(delta = -c_bot[0]) oct2d(size, c_side);
        translate([0, 0, z0 + c_bot[1]]) linear_extrude(z1 - z0 - c_bot[1] - c_top[1]) oct2d(size, c_side);
        translate([0, 0, z1 - eps]) linear_extrude(eps) offset(delta = -c_top[0]) oct2d(size, c_side);
    }
}

module box(p0, p1) { translate(p0) cube(p1 - p0); }

module hex_pocket(z0, z1) {
    // Hex nut pocket entered from the bed, with a first-layer flare
    hull() {
        translate([0, 0, z0 - eps]) cylinder(d = (nut_af + 2 * foot_c) / cos(30), h = eps, $fn = 6);
        translate([0, 0, z0 + foot_c]) cylinder(d = nut_af / cos(30), h = eps, $fn = 6);
    }
    translate([0, 0, z0]) cylinder(d = nut_af / cos(30), h = z1 - z0, $fn = 6);
}

// ---------- Wall cut-outs ----------
// Local frame: X = position along the wall, Y = depth from the outer face (inwards), Z = height.
module wall_frame(side) {
    if (side == "front") translate([0, -outer[1] / 2, 0]) children();
    else if (side == "rear") translate([0, outer[1] / 2, 0]) mirror([0, 1, 0]) children();
    else if (side == "left") translate([-outer[0] / 2, 0, 0]) multmatrix([[0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0]]) children();
    else if (side == "right") multmatrix([[0, -1, 0, outer[0] / 2], [1, 0, 0, 0], [0, 0, 1, 0]]) children();
}

// Rectangular opening through the wall with a 45 deg outward flare
module wall_rect(side, u, z, fl = 0) {
    depth = wall + lip_t + 1.5;
    wall_frame(side) {
        translate([u[0], -1, z[0]]) cube([u[1] - u[0], depth + 1, z[1] - z[0]]);
        if (fl > 0) hull() {
            translate([u[0] - fl, -1, z[0] - fl]) cube([u[1] - u[0] + 2 * fl, 1, z[1] - z[0] + 2 * fl]);
            translate([u[0], -1, z[0]]) cube([u[1] - u[0], 1 + fl, z[1] - z[0]]);
        }
    }
}

// Stadium (rounded slot) opening through the wall, axis normal to the wall
module wall_slot(side, c, size, fl = 0) {
    depth = wall + lip_t + 1.5;
    r = size[1] / 2;
    module stadium(rr, y0, h) {
        hull() for (s = [-1, 1])
            translate([c[0] + s * (size[0] / 2 - r), y0, c[1]]) rotate([-90, 0, 0]) cylinder(r = rr, h = h, $fn = 48);
    }
    wall_frame(side) {
        stadium(r, -1, depth + 1);
        if (fl > 0) hull() { stadium(r + fl, -1, 1); stadium(r, -1, 1 + fl); }
    }
}

// All edge openings. Each one crosses or touches the parting plane. In the lid every opening is
// extended down through the rim and lip, so it is a notch that opens upwards when the lid prints
// upside down; in the base the openings end at the rim. `which` selects the shell.
module edge_openings(which = "both") {
    lid = which == "lid";
    rim = -lip_h - 0.3;
    function zr(z) = lid ? [min(z[0], rim), z[1]] : z;
    // USB-A plug overmold (~16 x 8.5) merged with the Qwiic plug window
    wall_rect("front", [-15.2, 1.2], zr([-0.5, 8.3]), 0.6);
    wall_rect("front", [qwiic_x[0] - 0.75, -15.2 + eps], zr([-0.5, 3.7]), 0.6);
    // USB-C plug overmold; in the lid the lower half of the stadium is opened to the rim
    wall_slot("front", usb_c_c, [12.0, 7.0], 0.6);
    if (lid) wall_rect("front", [usb_c_c[0] - 6.0, usb_c_c[0] + 6.0], [rim, usb_c_c[1]], 0.6);
    // Battery JST-PH and I2S2 JST-SH (right wall)
    wall_rect("right", [batt_y[0] - 0.6, batt_y[1] + 0.6], zr([-0.6, 6.75]), 0.6);
    wall_rect("right", [i2s_y[0] - 0.6, i2s_y[1] + 0.6], zr([-0.6, 3.6]), 0.6);
    // microSD: wide opening with a deep flare so a fingernail reaches the card
    wall_rect("left", [sd_y[0] - 1.2, sd_y[1] + 1.2], zr([-1.5, 4.5]), 2.0);
    if (which == "base") {
        // DSI FPC exit below the PCB: the FPC runs on the floor from the underside socket
        wall_rect("front", [3.5, 17.6], [floor_top, split_z + eps]);
        // Recess for a down-angled USB-C plug head below the port
        wall_frame("front") translate([usbc_head_x[0], -1, base_bot - 1]) cube([usbc_head_x[1] - usbc_head_x[0], 1 + usbc_head_depth, split_z - base_bot + 1 + eps]);
    }
    if (lid) {
        // LED windows just above the PCB, so the three LEDs are visible from the front
        for (l = led_x) wall_rect("front", [l[0] - 0.5, l[1] + 0.5], [rim, 2.6]);
        // Camera FPC slot in the rear wall, centred on the CSI socket
        wall_rect("rear", [fpc_cx - fpc_slot[0] / 2, fpc_cx + fpc_slot[0] / 2], [rim, fpc_slot[1]]);
    }
}

// ---------- Base ----------
module rail_channels() {
    // Open-ended grooves beside the dovetail for the receiver jaws; their ceilings are 8.6 mm bridges
    xf_top = rail_w / 2 - rail_flank;                      // flank at the floor
    xf_c   = rail_w / 2 - foot_c * tan(rail_ang);          // flank where the foot chamfer starts
    for (s = [-1, 1]) mirror([s < 0 ? 1 : 0, 0, 0])
        rotate([90, 0, 0]) linear_extrude(height = outer[1] + 40, center = true)
            polygon([
                [xf_c - foot_c, base_bot - 1], [xf_c - foot_c, base_bot], [xf_c, base_bot + foot_c],
                [xf_top, floor_bot], [jaw_x, floor_bot], [jaw_x, base_bot + foot_c],
                [jaw_x + foot_c, base_bot], [jaw_x + foot_c, base_bot - 1]
            ]);
}

module latch_groove() {
    translate([-rail_w / 2 - 1, latch_y - latch_w / 2, base_bot - 1]) cube([rail_w + 2, latch_w, latch_d + 1]);
}

module clamp_block() {
    // FPC clamp seat behind the rear wall, solid down to the bed
    bx = [fpc_cx - clamp_size[0] / 2, fpc_cx + clamp_size[0] / 2];
    by = [outer[1] / 2 - 2, clamp_y0 + clamp_gap + clamp_size[1]];
    difference() {
        translate([(bx[0] + bx[1]) / 2, (by[0] + by[1]) / 2, 0])
            hull() {
                cprism([bx[1] - bx[0], by[1] - by[0]], base_bot, split_z - 1.0, edge_c, bed_c);
                // Rounded-off rear top edge so the FPC bends over a 1 mm chamfer
                translate([0, -0.5, 0]) cprism([bx[1] - bx[0], by[1] - by[0] - 1], base_bot, split_z, edge_c);
            }
        for (s = [-1, 1]) translate([fpc_cx + s * clamp_screw_dx, clamp_screw_y, 0]) {
            translate([0, 0, base_bot - 1]) cylinder(d = m3_d, h = 20);
            nut_top = split_z + clamp_size[2] - clamp_screw_len + 0.1 + nut_h;
            hex_pocket(base_bot, nut_top);
        }
    }
}

module case_base() {
    color(c_black) difference() {
        union() {
            difference() {
                cprism(outer, base_bot, split_z, edge_c, bed_c, [seam_c, seam_c]);
                rail_channels();
            }
            clamp_block();
        }
        // Cavity
        translate([-inner[0] / 2, -inner[1] / 2, floor_top]) cube([inner[0], inner[1], 20]);
        // Rebate for the lid lip
        difference() {
            translate([0, 0, split_z - lip_h - 0.1]) linear_extrude(5)
                square([inner[0] + 2 * (lip_t + lip_gap), inner[1] + 2 * (lip_t + lip_gap)], center = true);
            translate([0, 0, split_z - lip_h - 1]) linear_extrude(10) square(inner, center = true);
        }
        latch_groove();
        edge_openings("base");
        // Through-bolt holes and nut pockets from below
        for (h = pcb_holes) translate([h[0], h[1], 0]) {
            translate([0, 0, base_bot - 1]) cylinder(d = m3_d, h = 20);
            hex_pocket(base_bot, seat_z - bolt_len + 0.1 + nut_h);
        }
    }
    // Board standoffs
    color(c_black) for (h = pcb_holes) translate([h[0], h[1], floor_top - eps]) difference() {
        cylinder(d = standoff_d, h = -pcb_t - floor_top + eps);
        translate([0, 0, -1]) cylinder(d = m3_d, h = 10);
    }
}

// ---------- Lid ----------
module button_tab_cuts(x) {
    // U-shaped slot around a thin flexure; the tab face sits 0.5 mm in front of the actuator
    y_out = -outer[1] / 2;
    y_in  = -inner[1] / 2;
    hw = tab_w / 2;
    z0 = -lip_h - 0.5;
    for (s = [-1, 1]) box([x + s * hw - (s > 0 ? 0 : tab_slot), y_out - 1, z0], [x + s * hw + (s > 0 ? tab_slot : 0), y_in + 1, tab_root_z]);
    // Material between the tab and the board (actuator tip enters the wall zone)
    box([x - hw - tab_slot, tab_face_y, z0], [x + hw + tab_slot, y_in + 1, tab_root_z]);
    // Outer recess that thins the tab to tab_t and marks the button
    box([x - hw - tab_slot, y_out - 1, z0], [x + hw + tab_slot, tab_face_y - tab_t, tab_root_z]);
    // Free end stops at the rim (lip removed under the tab)
    box([x - hw - tab_slot, y_out - 1, z0], [x + hw + tab_slot, y_in + 1, split_z]);
}

module lid_windows() {
    m = 0.6;   // clearance around top-side parts
    // GPIO 2x10 header, I3C socket, mikroBUS bay (both sockets + CSI area), boot switch
    box([gpio_box[0][0] - m, gpio_box[0][1] - m, ceiling_z - 1], [gpio_box[1][0] + m, inner[1] / 2, lid_top + 1]);
    box([i3c_box[0][0] - m, i3c_box[0][1] - m, ceiling_z - 1], [i3c_box[1][0] + m, i3c_box[1][1] + m, lid_top + 1]);
    box([mikrobus_box[0][0] - m, mikrobus_box[0][1] - m, ceiling_z - 1], [mikrobus_box[1][0] + m, inner[1] / 2, lid_top + 1]);
    box([boot_sw_box[0][0] - 0.7, boot_sw_box[0][1] - 0.7, ceiling_z - 1], [boot_sw_box[1][0] + 0.7, boot_sw_box[1][1] + 0.7, lid_top + 1]);
    // Vents over the SoM
    vx0 = (som_box[0][0] + som_box[1][0]) / 2 - (vent_n - 1) * vent_pitch / 2;
    for (i = [0 : vent_n - 1]) translate([vx0 + i * vent_pitch, 0, 0])
        box([-vent_w / 2, vent_y[0], ceiling_z - 1], [vent_w / 2, vent_y[1], lid_top + 1]);
}

module case_lid() {
    color(c_orange) difference() {
        union() {
            cprism(outer, split_z, lid_top, edge_c, [seam_c, seam_c], bed_c);
            // Alignment lip that drops into the base rebate
            translate([0, 0, split_z - lip_h]) linear_extrude(lip_h + eps) difference() {
                square([inner[0] + 2 * lip_t, inner[1] + 2 * lip_t], center = true);
                square(inner, center = true);
            }
        }
        translate([-inner[0] / 2, -inner[1] / 2, split_z - 5]) cube([inner[0], inner[1], ceiling_z + 5]);
        edge_openings("lid");
        for (x = [btn_user_x, btn_reset_x]) button_tab_cuts(x);
        lid_windows();
        // Debossed label on the top face
        translate([label_pos[0], label_pos[1], lid_top - label_depth]) linear_extrude(label_depth + 1)
            text(label_text, size = label_size, font = label_font, halign = "center", valign = "center", spacing = 1.1);
        translate([coral_base[0], coral_base[1], lid_top - coral_depth]) linear_extrude(coral_depth + 1)
            coral_2d(height = coral_h, stroke = coral_stroke, depth = coral_levels, seed = coral_seed);
        // Antenna pocket in the ceiling
        box([ant_box[0][0], ant_box[0][1], ceiling_z - 1], [ant_box[1][0], ant_box[1][1], ceiling_z + ant_depth]);
        // Through-bolt counterbores
        for (h = pcb_holes) translate([h[0], h[1], 0]) {
            translate([0, 0, -5]) cylinder(d = m3_d, h = 30);
            translate([0, 0, seat_z]) cylinder(d = m3_head_d, h = 10);
        }
    }
    // Pillars that press the PCB onto the base standoffs. Above the neck each pillar widens and is
    // tied to the nearest side wall so the head counterbore keeps a closed wall.
    color(c_orange) for (h = pcb_holes) translate([h[0], h[1], split_z]) difference() {
        union() {
            cylinder(d = pillar_d, h = pillar_neck_z + eps);
            hull() {
                translate([0, 0, pillar_neck_z]) cylinder(d = pillar_d, h = eps);
                translate([0, 0, pillar_neck_z + 0.7]) linear_extrude(ceiling_z - split_z - pillar_neck_z - 0.7 + eps) hull() {
                    circle(d = pillar_top_d);
                    sx = sign(h[0]);
                    translate([sx > 0 ? 0 : -(inner[0] / 2 - abs(h[0])) - 0.5, -pillar_top_d / 2]) square([inner[0] / 2 - abs(h[0]) + 0.5, pillar_top_d]);
                }
            }
        }
        translate([0, 0, -1]) cylinder(d = m3_d, h = 20);
        translate([0, 0, seat_z - split_z]) cylinder(d = m3_head_d, h = 10);
    }
}

// ---------- FPC clamp bar ----------
module case_fpc_clamp() {
    color(c_black) difference() {
        translate([fpc_cx, clamp_screw_y, split_z]) cprism([clamp_size[0], clamp_size[1]], 0, clamp_size[2], edge_c, [0, 0], [1.0, 1.0]);
        // Shallow recess over the FPC so the bar grips it without crushing
        box([fpc_cx - fpc_slot[0] / 2, clamp_y0, split_z - 1], [fpc_cx + fpc_slot[0] / 2, clamp_y0 + 20, split_z + clamp_relief]);
        for (s = [-1, 1]) translate([fpc_cx + s * clamp_screw_dx, clamp_screw_y, -5]) cylinder(d = m3_d, h = 20);
    }
}

// ---------- Board (for assembly renders only) ----------
module board(alpha = 1) {
    color([0.18, 0.42, 0.27, alpha]) translate(board_offset) import(board_stl, convexity = 6);
}

// ASSUMPTION: M.2 2230 E-key card envelope (not in the STL): 22 x 30 card on the standoff at
// (-25, -12.75), top components up to 1.5 mm, plus u.FL plug height.
module m2_card_envelope() {
    color([0.12, 0.3, 0.55, 0.6]) box([-36, -14.3, 2.6], [-14, 17, 5.6]);
}

// ---------- Keep-out volume for decorative overgrowth (coralgen) ----------
// Space that anything grown onto the base must leave free. Port zones are full-height columns,
// so a branch crossing them could not leave an unsupported stub when it is cut away.
ko_tall       = 200;      // height of the open-ended columns above the bed
ko_wall_bite  = 0.2;      // cut faces sit this far inside wall material, never coplanar with it
ko_lift_gap   = 0.6;      // free play around the lid as it is lifted off vertically
ko_front_d    = 30;       // USB-A/C plugs, Qwiic plug, buttons and LEDs on the front face
ko_side_d     = 18;       // finger and plug access to the microSD, battery and I2S sockets
ko_side_m     = 4;        // extra width beside each side opening for the fingertip / plug body
ko_rear_m     = 4;        // around the FPC clamp bar and its two screw heads
ko_rear_d     = 25;       // free bend space for the camera FPC behind the clamp

// Every functional void of the base (cavity, lid rebate, port openings, bolt holes, nut pockets,
// rail channels, latch groove), so grown material can never block one. The cavity is widened into
// the wall so cut faces never coincide with the inner wall.
module base_cut() {
    box([-inner[0] / 2 - ko_wall_bite, -inner[1] / 2 - ko_wall_bite, floor_top],
        [inner[0] / 2 + ko_wall_bite, inner[1] / 2 + ko_wall_bite, ko_tall]);
    translate([0, 0, split_z - lip_h - 0.1 - ko_wall_bite]) linear_extrude(ko_tall)
        square([inner[0] + 2 * (lip_t + lip_gap + ko_wall_bite), inner[1] + 2 * (lip_t + lip_gap + ko_wall_bite)], center = true);
    edge_openings("base");
    rail_channels();
    latch_groove();
    for (h = pcb_holes) translate([h[0], h[1], 0]) {
        translate([0, 0, base_bot - 1]) cylinder(d = m3_d, h = 20);
        hex_pocket(base_bot, seat_z - bolt_len + 0.1 + nut_h);
    }
    for (s = [-1, 1]) translate([fpc_cx + s * clamp_screw_dx, clamp_screw_y, 0]) {
        translate([0, 0, base_bot - 1]) cylinder(d = m3_d, h = 20);
        hex_pocket(base_bot, split_z + clamp_size[2] - clamp_screw_len + 0.1 + nut_h);
    }
}

module base_keepout() {
    hx = outer[0] / 2;
    hy = outer[1] / 2;
    zb = base_bot - 1;
    // The lid's lift path: outer footprint plus free play above the parting plane
    translate([0, 0, split_z - ko_wall_bite]) linear_extrude(ko_tall)
        offset(delta = ko_lift_gap) oct2d(outer, edge_c);
    // Front face
    box([-hx - ko_lift_gap, -hy - ko_front_d, zb], [hx + ko_lift_gap, -hy + wall + ko_wall_bite, ko_tall]);
    // Left: microSD
    box([-hx - ko_side_d, sd_y[0] - 1.2 - 2.0 - ko_side_m, zb], [-hx + wall + ko_wall_bite, sd_y[1] + 1.2 + 2.0 + ko_side_m, ko_tall]);
    // Right: battery JST-PH and I2S JST-SH
    box([hx - wall - ko_wall_bite, batt_y[0] - 0.6 - ko_side_m, zb], [hx + ko_side_d, i2s_y[1] + 0.6 + ko_side_m, ko_tall]);
    // Rear: FPC clamp block, clamp bar screws (driven from above) and the camera FPC
    box([fpc_cx - clamp_size[0] / 2 - ko_rear_m, hy - wall - ko_wall_bite, zb],
        [fpc_cx + clamp_size[0] / 2 + ko_rear_m, clamp_y0 + clamp_gap + clamp_size[1] + ko_rear_d, ko_tall]);
}

// ---------- Print orientations ----------
module base_print()  { translate([0, 0, -base_bot]) case_base(); }
module base_keepout_print() { translate([0, 0, -base_bot]) base_keepout(); }
module base_cut_print() { translate([0, 0, -base_bot]) base_cut(); }
module lid_print()   { translate([0, 0, lid_top]) rotate([180, 0, 0]) case_lid(); }
module clamp_print() { translate([0, 0, split_z + clamp_size[2]]) rotate([180, 0, 0]) case_fpc_clamp(); }

part = "none";
if (part == "base") base_print();
else if (part == "lid") lid_print();
else if (part == "clamp") clamp_print();
else if (part == "base_keepout") base_keepout_print();
else if (part == "base_cut") base_cut_print();
// Assembly-frame exports, used by the clearance measurement
else if (part == "base_asm") case_base();
else if (part == "lid_asm") case_lid();
else if (part == "clamp_asm") case_fpc_clamp();
