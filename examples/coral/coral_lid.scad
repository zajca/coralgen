// Coral lid: the case lid split at the ceiling into a ring and a flat top plate, so coral can grow
// from the plate's top face. A one-piece lid printed top-up would need a 74 x 59 mm ceiling bridge.
//
//   ring  - lid walls, lip, pillars and button flexures (case_lid below the ceiling). Prints upside
//           down like the standard lid: every wall opening is a notch that opens upwards.
//   plate - the ceiling with its windows, vents, label and antenna pocket; prints flat, bottom on the
//           bed (the antenna pocket roof is a 10 mm bridge). coralgen grows coral from its top face.
// The four through bolts clamp plate, ring, PCB and base; their heads sit on the plate top, so they
// are M3x20 instead of M3x16 (head at lid_top, tip 20 mm lower passes the nut in the base pocket).
//
// Parts (-D 'part="..."'):
//   ring_print, plate_print - printable parts in print orientation
//   plate_cut, plate_keepout - not parts: coralgen volumes in the plate print frame
//   crawl_host, crawl_cut, crawl_keepout - coralgen "crawl" run over the whole lid (ring + plate),
//            case frame: the coral creeps over the top and pours down the sides
//   assembly - base, ring and plate in the case frame
include <../case/case.scad>

coral_bolt_len  = 20;       // M3 through bolts with the head on the plate top
// Coral keep-out over the plate top (plate print frame)
ko_window_m     = 2.0;      // clearance around the GPIO, I3C, mikroBUS and boot switch windows
ko_vent_m       = 2.0;      // around the SoM vents, so the hot air rises freely
ko_head_d       = 10;       // driver and fingers around each bolt head
ko_label_m      = 1.5;      // keeps the CORALWATCH label readable

// Crawl keep-out on the lid sides
ko_open_m       = 1.5;      // around every wall opening, button flexure, LED window and the FPC slot
ko_seam_m       = 1.5;      // coral stops this far above the base/lid parting line

plate_t         = lid_top - ceiling_z;

module lid_ring() {
    intersection() {
        case_lid();
        translate([-100, -100, split_z - lip_h - 1]) cube([200, 200, ceiling_z - (split_z - lip_h - 1)]);
    }
}

module plate_label() {
    translate([label_pos[0], label_pos[1], lid_top - label_depth]) linear_extrude(label_depth + 1)
        text(label_text, size = label_size, font = label_font, halign = "center", valign = "center", spacing = 1.1);
}

module lid_plate() {
    color(c_orange) difference() {
        cprism(outer, ceiling_z, lid_top, edge_c, [0, 0], bed_c);
        lid_windows();
        plate_label();
        box([ant_box[0][0], ant_box[0][1], ceiling_z - 1], [ant_box[1][0], ant_box[1][1], ceiling_z + ant_depth]);
        for (h = pcb_holes) translate([h[0], h[1], ceiling_z - 1]) cylinder(d = m3_d, h = plate_t + 2);
    }
}

// Plate frame: plate bottom (ceiling_z) at z = 0
module plate_place() { translate([0, 0, -ceiling_z]) children(); }

module plate_cut() {
    // Everything under the plate: root extensions must not reach into the case
    plate_place() translate([-100, -100, ceiling_z - 50]) cube([200, 200, 50]);
}

module plate_keepout() {
    plate_place() {
        window_columns();
        for (h = pcb_holes) translate([h[0], h[1], ceiling_z]) cylinder(d = ko_head_d, h = ko_tall);
        translate([label_pos[0], label_pos[1], ceiling_z]) linear_extrude(ko_tall) offset(delta = ko_label_m)
            text(label_text, size = label_size, font = label_font, halign = "center", valign = "center", spacing = 1.1);
    }
}

// Vertical columns over the lid windows and vents (same boxes as case.scad lid_windows)
module window_columns() {
    m = 0.6;
    w = ko_window_m;
    v = ko_vent_m;
    module col(p0, p1, g) translate([p0[0] - g, p0[1] - g, ceiling_z]) cube([p1[0] - p0[0] + 2 * g, p1[1] - p0[1] + 2 * g, ko_tall]);
    col([gpio_box[0][0] - m, gpio_box[0][1] - m], [gpio_box[1][0] + m, inner[1] / 2], w);
    col([i3c_box[0][0] - m, i3c_box[0][1] - m], [i3c_box[1][0] + m, i3c_box[1][1] + m], w);
    col([mikrobus_box[0][0] - m, mikrobus_box[0][1] - m], [mikrobus_box[1][0] + m, inner[1] / 2], w);
    col([boot_sw_box[0][0] - 0.7, boot_sw_box[0][1] - 0.7], [boot_sw_box[1][0] + 0.7, boot_sw_box[1][1] + 0.7], w);
    vx0 = (som_box[0][0] + som_box[1][0]) / 2 - (vent_n - 1) * vent_pitch / 2;
    col([vx0 - vent_w / 2, vent_y[0]], [vx0 + (vent_n - 1) * vent_pitch + vent_w / 2, vent_y[1]], v);
}
// ---------- Crawl run over the whole lid (case frame) ----------
module crawl_host() { lid_ring(); lid_plate(); }

// The case interior: relief sunk into the walls or plate must never reach inside
module crawl_cut() {
    translate([-inner[0] / 2, -inner[1] / 2, split_z - 10]) cube([inner[0], inner[1], ceiling_z - split_z + 10]);
}

module crawl_keepout() {
    // Top: windows, vents, bolt heads and label, from below the plate so sunk relief is cut too
    translate([0, 0, -plate_t - 1]) {
        window_columns();
        for (h = pcb_holes) translate([h[0], h[1], ceiling_z]) cylinder(d = ko_head_d, h = ko_tall);
        translate([label_pos[0], label_pos[1], ceiling_z]) linear_extrude(ko_tall) offset(delta = ko_label_m)
            text(label_text, size = label_size, font = label_font, halign = "center", valign = "center", spacing = 1.1);
    }
    // Sides: every opening of the lid walls, grown by ko_open_m
    minkowski() {
        union() {
            edge_openings("lid");
            for (x = [btn_user_x, btn_reset_x]) button_tab_cuts(x);
        }
        cube(2 * ko_open_m, center = true);
    }
    // Below the seam: the base is not part of this run
    translate([-100, -100, split_z - 50]) cube([200, 200, 50 + ko_seam_m]);
}

module ring_print()  { translate([0, 0, ceiling_z]) rotate([180, 0, 0]) lid_ring(); }
module plate_print() { plate_place() lid_plate(); }

part = "assembly";
if (part == "ring_print") ring_print();
else if (part == "plate_print") plate_print();
else if (part == "plate_cut") plate_cut();
else if (part == "plate_keepout") plate_keepout();
else if (part == "crawl_host") crawl_host();
else if (part == "crawl_cut") crawl_cut();
else if (part == "crawl_keepout") crawl_keepout();
else if (part == "assembly") { case_base(); lid_ring(); lid_plate(); }
