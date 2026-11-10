// Procedural branching coral (own design, not traced from any artwork): a recursive tree of
// round-capped strokes in 2D. Stroke width and depth are parameters so a debossed or raised
// version stays printable (strokes >= 1 mm, no wide filled areas).
//   coral_2d(height = 20, stroke = 1.2, depth = 4, spread = 22, seed = 3)

function coral_rnd(seed, i) = (sin(seed * 127.1 + i * 311.7) * 43758.5453) % 1;   // deterministic, -1..1

module coral_stroke(a, b, w) { hull() { translate(a) circle(d = w, $fn = 16); translate(b) circle(d = w, $fn = 16); } }

module coral_branch(p, ang, len, w, depth, spread, seed, i) {
    q = p + len * [sin(ang), cos(ang)];
    coral_stroke(p, q, w);
    if (depth > 0) {
        j = coral_rnd(seed, i);
        coral_branch(q, ang - spread * (0.7 + 0.3 * abs(j)), len * 0.8, max(w * 0.85, 1.0), depth - 1, spread, seed, 2 * i + 1);
        coral_branch(q, ang + spread * (0.7 + 0.3 * abs(coral_rnd(seed, i + 17))), len * (0.74 + 0.1 * j), max(w * 0.85, 1.0), depth - 1, spread, seed, 2 * i + 2);
    }
}

module coral_2d(height = 20, stroke = 1.2, depth = 4, spread = 22, seed = 3) {
    trunk = height * 0.3;
    coral_branch([0, 0], 0, trunk, stroke * 1.4, depth, spread, seed, 1);
    // two side stems from the base give the fan shape typical of branching corals
    coral_branch([0, trunk * 0.3], -38, trunk * 0.8, stroke * 1.2, depth - 1, spread, seed + 1, 1);
    coral_branch([0, trunk * 0.3], 38, trunk * 0.8, stroke * 1.2, depth - 1, spread, seed + 2, 1);
}
