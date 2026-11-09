// static/sprites/drone.js: the drone seen from above, nose along +x,
// about 40 px across, in the robot's colour col.  Helpers rr(), dot(),
// arm() and the canvas ctx come from the page.
// Drone: X frame, four rotors, red nose
SPRITES.drone = function (c, col) {
  ctx.strokeStyle = "#3a3a3c"; ctx.lineWidth = 3; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(-14, -14); ctx.lineTo(14, 14); ctx.moveTo(-14, 14); ctx.lineTo(14, -14); ctx.stroke();
  [[14, 14], [14, -14], [-14, 14], [-14, -14]].forEach(function (p) {
    ctx.strokeStyle = "rgba(120,120,120,0.55)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(p[0], p[1], 9, 0, 7); ctx.stroke();
    dot(p[0], p[1], 2.5, "#1c1c1e");
  });
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(-9, -6, 18, 12, 4); ctx.fill(); ctx.stroke();
  dot(8, 0, 2, "#ff5348"); dot(-7, 0, 1.6, "#4fd1ff");
};
