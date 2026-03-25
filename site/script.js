const canvas = document.getElementById("ascii-field");

if (canvas) {
  const context = canvas.getContext("2d");
  const chars = "01RB<>[]{}=+*-:/\\|$#@;%&~!?reportbridgeEDGEstatus";
  const columns = [];
  let width = 0;
  let height = 0;
  let cell = 13;
  let trailDepth = 3;

  function pickChar() {
    return chars[Math.floor(Math.random() * chars.length)];
  }

  function resize() {
    const ratio = window.devicePixelRatio || 1;
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    cell = width < 700 ? 11 : 13;
    trailDepth = width < 700 ? 4 : 5;
    columns.length = Math.ceil(width / cell) + 2;

    for (let i = 0; i < columns.length; i += 1) {
      columns[i] = {
        x: i * cell,
        y: Math.random() * height,
        speed: 1 + Math.random() * 2.4,
        glyph: pickChar(),
        drift: (Math.random() - 0.5) * 0.5,
      };
    }
  }

  function frame() {
    context.fillStyle = "rgba(7, 17, 26, 0.13)";
    context.fillRect(0, 0, width, height);
    context.font = `${cell}px "IBM Plex Mono", Consolas, monospace`;
    context.textBaseline = "top";

    for (const column of columns) {
      for (let step = trailDepth; step >= 0; step -= 1) {
        const alpha = step === 0 ? 0.82 : 0.14 + (trailDepth - step) * 0.08;
        context.fillStyle = `rgba(125, 247, 209, ${alpha})`;
        context.fillText(pickChar(), column.x, column.y - step * (cell * 1.1));
      }

      column.y += column.speed;
      column.x += column.drift;

      if (Math.random() > 0.9) {
        column.glyph = pickChar();
      }

      if (column.y > height + cell * 2 || column.x < -cell || column.x > width + cell) {
        column.y = -Math.random() * height * 0.35;
        column.x = Math.random() * width;
        column.speed = 0.6 + Math.random() * 1.8;
        column.drift = (Math.random() - 0.5) * 0.35;
        column.glyph = pickChar();
      }
    }

    requestAnimationFrame(frame);
  }

  resize();
  requestAnimationFrame(frame);
  window.addEventListener("resize", resize);
}
