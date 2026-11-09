// static/sprites/lolibot.js: the lolibot seen from above, nose along +x,
// about 40 px across, in the robot's colour col.  Helpers rr(), dot(),
// arm() and the canvas ctx come from the page.
// Stylised LoliBot (openhardwareconf.org): PCB chassis in the robot's
// colour, yellow-hub wheels, red 18650 battery, ESP32, underglow
SPRITES.lolibot = function (c, col) {
  var glow = ctx.createRadialGradient(0, 0, 4, 0, 0, 30);
  glow.addColorStop(0, "rgba(62,207,142,0.45)"); glow.addColorStop(1, "rgba(62,207,142,0)");
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(0, 0, 30, 0, 7); ctx.fill();
  function wheel(wy) { rr(-2, wy - 5, 22, 10, 5, "#1c1c1e"); rr(4, wy - 2, 10, 4, 2, "#f0b429"); }
  wheel(-17); wheel(17);
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(-16, -13); ctx.quadraticCurveTo(-21, 0, -16, 13); ctx.lineTo(8, 13);
  ctx.quadraticCurveTo(22, 8, 25, 0); ctx.quadraticCurveTo(22, -8, 8, -13); ctx.closePath(); ctx.fill(); ctx.stroke();
  rr(-2, -10, 6, 20, 3, "#c03535"); ctx.fillStyle = "#e8e2d4"; ctx.fillRect(-2, -10, 6, 2.5);
  rr(-13, -6, 8, 12, 1.5, "#232323");
  dot(18, 0, 1.8, "#ff5348");
  ctx.fillStyle = "#cfcfcf"; ctx.strokeStyle = "#8a8a8a"; ctx.beginPath(); ctx.arc(-17, 0, 2.5, 0, 7); ctx.fill(); ctx.stroke();
};
