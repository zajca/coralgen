// Render: case with the two-part coral lid and the grown coral (coralgen output, plate frame).
include <coral_lid.scad>
color("#FA6831") translate([0, 0, ceiling_z]) import("out/coral_lid_coral_only.stl", convexity = 10);
