// static/sprites/irobot.js: an iRobot Create 3 seen from above, nose along +x,
// about 40 px across, in the robot's colour col: the round base, the bumper
// at the front, the Pi board on top where the bin used to be.  Helpers rr(),
// dot() and the canvas ctx come from the page.
SPRITES.irobot = function (c, col) {
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(0, 0, 19, 0, 7); ctx.fill(); ctx.stroke();        // the disc
  ctx.strokeStyle = "#1c1c1e"; ctx.lineWidth = 4; ctx.lineCap = "round";     // bumper
  ctx.beginPath(); ctx.arc(0, 0, 17, -1.1, 1.1); ctx.stroke();
  ctx.strokeStyle = "rgba(0,0,0,0.25)"; ctx.lineWidth = 1;                  // wheel wells
  rr(-4, -16, 9, 5, 2, "#2a2a2c"); rr(-4, 11, 9, 5, 2, "#2a2a2c");
  rr(-12, -7, 15, 14, 2, "#2f7d3a");                                        // the Pi
  rr(-10, -5, 4, 3, 1, "#9a9a9a"); rr(-10, 1, 4, 3, 1, "#9a9a9a");           // USB
  for (var i = -5; i < 6; i += 2.5) dot(1, i, 0.6, "#f0b429");               // GPIO
  dot(8, 0, 3, "#e9e4d8"); dot(8, 0, 1.4, "#4fd1ff");                        // button / light ring
  dot(-16, 0, 1.5, "#ff5348");                                               // dock contacts
};
