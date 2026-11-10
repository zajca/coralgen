// Render: closed case with the four coral corner clips (coralgen output in the base print frame).
include <coral_clips.scad>
color("#FA6831") translate([0, 0, base_bot]) import("out/coral_clips_coral_only.stl", convexity = 10);
