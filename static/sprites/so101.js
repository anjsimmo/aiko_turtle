// static/sprites/so101.js: the so101 seen from above, nose along +x,
// about 40 px across, in the robot's colour col.  Helpers rr(), dot(),
// arm() and the canvas ctx come from the page.
// SO-101: an arm on a square base plate; it does not drive
SPRITES.so101 = function (c, col) {
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(-14, -14, 28, 28, 3); ctx.fill(); ctx.stroke();
  [[-10, -10], [10, -10], [-10, 10], [10, 10]].forEach(function (p) { dot(p[0], p[1], 1.5, "#5a5a5c"); });
  rr(-6, -6, 12, 12, 2, "#2a2a2c");
  arm(0, 0, 14, 12, "#f0b429");
};
