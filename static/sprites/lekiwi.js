// static/sprites/lekiwi.js: the lekiwi seen from above, nose along +x,
// about 40 px across, in the robot's colour col.  Helpers rr(), dot(),
// arm() and the canvas ctx come from the page.
// LeKiwi: round omni base with three wheels at 120 degrees, SO-101 arm forward
SPRITES.lekiwi = function (c, col) {
  [90, 210, 330].forEach(function (deg) {
    ctx.save(); ctx.rotate(deg * Math.PI / 180); rr(-5, 15, 10, 6, 2, "#1c1c1e"); ctx.restore();
  });
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(0, 0, 16, 0, 7); ctx.fill(); ctx.stroke();
  dot(0, 0, 4, "#2a2a2c");
  arm(0, 0, 14, 12, "#e9e4d8");
  dot(-9, 0, 2, "#4fd1ff");                                                          // camera
};
