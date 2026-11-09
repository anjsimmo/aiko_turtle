// static/sprites/xgo.js: the xgo seen from above, nose along +x,
// about 40 px across, in the robot's colour col.  Helpers rr(), dot(),
// arm() and the canvas ctx come from the page.
// XGO: a quadruped seen from above, legs splayed, head with camera forward
SPRITES.xgo = function (c, col) {
  [[10, 13, 25], [10, -13, -25], [-12, 13, 155], [-12, -13, -155]].forEach(function (l) {
    ctx.save(); ctx.translate(l[0], l[1]); ctx.rotate(l[2] * Math.PI / 180);
    rr(-2, -3, 13, 6, 3, "#3a3a3c"); dot(12, 0, 3, "#1c1c1e"); ctx.restore();
  });
  rr(-20, -2, 6, 4, 2, "#3a3a3c");                                                  // tail
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(-18, -9, 34, 18, 6); ctx.fill(); ctx.stroke();      // body
  rr(12, -7, 14, 14, 4, "#2a2a2c");                                                 // head
  dot(23, 0, 2.5, "#4fd1ff"); dot(22, -5, 1.2, "#ff5348"); dot(22, 5, 1.2, "#ff5348"); // camera, LEDs
  rr(13, -11, 5, 3, 1, "#2a2a2c"); rr(13, 8, 5, 3, 1, "#2a2a2c");                   // ears
};
