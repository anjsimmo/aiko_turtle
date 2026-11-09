// static/sprites/pi.js: the pi seen from above, nose along +x,
// about 40 px across, in the robot's colour col.  Helpers rr(), dot(),
// arm() and the canvas ctx come from the page.
// Raspberry Pi: green board, small display, USB and Ethernet, GPIO header
SPRITES.pi = function (c, col) {
  ctx.fillStyle = "#2f7d3a"; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(-17, -12, 34, 24, 2); ctx.fill(); ctx.stroke();
  rr(-15, -10, 18, 20, 1, col); rr(-13, -8, 14, 16, 1, "#101418");                 // display
  ctx.fillStyle = "#4fd1ff"; ctx.font = "7px 'IBM Plex Mono',monospace"; ctx.fillText("hi", -9, 2);
  rr(6, -11, 5, 22, 1, "#1c1c1e"); for (var i = -9; i < 11; i += 3) dot(8.5, i, 0.7, "#f0b429"); // GPIO
  rr(12, -10, 5, 8, 1, "#9a9a9a"); rr(12, 2, 5, 8, 1, "#9a9a9a");                  // USB, Ethernet
  dot(-16, 9, 1.2, "#ff5348"); dot(-16, 6, 1.2, "#3ecf8e");                        // PWR, ACT
};
