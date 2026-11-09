// static/sprites/turtle.js: the turtle seen from above, nose along +x,
// about 40 px across, in the robot's colour col.  Helpers rr(), dot(),
// arm() and the canvas ctx come from the page.
SPRITES.turtle = function (c, col) {
  var skin = "#8fb55a";
  [[-7, 12, 40], [7, 12, 140], [7, -12, -140], [-7, -12, -40]].forEach(function (l) {       // legs
    ctx.save(); ctx.translate(l[0], l[1]); ctx.rotate(l[2] * Math.PI / 180);
    rr(-3, -3, 12, 6, 3, skin); ctx.restore();
  });
  rr(-22, -2, 8, 4, 2, skin);                                                            // tail
  dot(18, 0, 6, skin); dot(21, -2.5, 1.2, "#1c1c1e"); dot(21, 2.5, 1.2, "#1c1c1e");   // head
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;                    // shell
  ctx.beginPath(); ctx.ellipse(0, 0, 16, 13, 0, 0, 7); ctx.fill(); ctx.stroke();
  ctx.strokeStyle = "rgba(0,0,0,0.25)"; ctx.beginPath(); ctx.ellipse(0, 0, 8, 6, 0, 0, 7); ctx.stroke();
  [0, 60, 120, 180, 240, 300].forEach(function (deg) {
    var a = deg * Math.PI / 180; ctx.beginPath(); ctx.moveTo(8 * Math.cos(a), 6 * Math.sin(a)); ctx.lineTo(15 * Math.cos(a), 12 * Math.sin(a)); ctx.stroke();
  });
};
