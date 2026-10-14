#!/usr/bin/env python3
"""End-to-end RGBA test on a real compositor.

Run from the repository root in the build environment (requires Pillow):
    python kitty_tests/manual_background_opacity.py
This opens temporary kitty windows, never changes the user's configuration,
and saves screenshots to the directory printed on completion.
"""

import base64
import collections
import subprocess
import sys
import tempfile
import time
from pathlib import Path

COLORS = [(48 + i * 11, 64 + i * 7, 192 - i * 5) for i in range(16)]
# A seventeenth distinct background produced by reverse video, plus indexed red.
REVERSED = (31, 123, 207)
INDEXED = (205, 49, 49)


def fixture():
    sys.stdout.write('\x1b[2J\x1b[H\x1b[?25l')
    for row, (r, g, b) in enumerate(COLORS, 1):
        sys.stdout.write(f'\x1b[{row};1H\x1b[48;2;{r};{g};{b}m\x1b[38;2;255;255;255m')
        sys.stdout.write(' ' * 20 + '██  Aa Ω あ  ' + ' ' * 12)
    r, g, b = REVERSED
    sys.stdout.write(f'\x1b[17;1H\x1b[0m\x1b[38;2;{r};{g};{b}m\x1b[7m' + ' ' * 40)
    sys.stdout.write('\x1b[18;1H\x1b[0m\x1b[41m' + ' ' * 40)
    sys.stdout.write('\x1b[19;1H\x1b[0m\x1b[4;9mDecorations\x1b[0m')
    if '--layers' in sys.argv:
        # Exercise both the split BG/images/FG path and positive-z images.
        data = base64.b64encode(bytes((0, 255, 0, 255)) * 4).decode('ascii')
        for row, z in ((20, -1), (21, 1)):
            sys.stdout.write(f'\x1b[{row};1H\x1b_Ga=T,f=32,s=2,v=2,c=4,r=1,z={z},q=2;{data}\x1b\\')
        sys.stdout.write('\x1b[22;1H\x1b[?25h')
    sys.stdout.write('\x1b]2;opacity-fixture-ready\x07')
    sys.stdout.flush()
    time.sleep(120)


def main():
    from PIL import Image

    root = Path(__file__).resolve().parent.parent
    launcher = root / 'kitty/launcher/kitty'
    directory = Path(tempfile.mkdtemp(prefix='kitty-opacity-', dir='/tmp'))
    print(f'Screenshots: {directory}', flush=True)
    # Custom colors avoid depending on a user's theme. The explicit list entry
    # tests that all-colors mode takes precedence over individual opacities.
    first = '#%02x%02x%02x' % COLORS[0]
    for enabled, opacity, layers in ((True, 0.4, False), (False, 0.4, False), (True, 0.0, False), (True, 1.0, False), (True, 0.4, True)):
        name = f'{"on" if enabled else "off"}-{opacity}' + ('-layers' if layers else '')
        socket = directory / (name + '.sock')
        png = directory / (name + '.png')
        command = [
            str(launcher),
            '--config',
            'NONE',
            '--listen-on',
            f'unix:{socket}',
            '--title',
            'opacity-fixture-starting',
            '-o',
            'allow_remote_control=yes',
            '-o',
            'linux_display_server=wayland',
            '-o',
            'background=#101010',
            '-o',
            'foreground=#ffffff',
            '-o',
            'color1=#cd3131',
            '-o',
            'initial_window_width=800',
            '-o',
            'initial_window_height=700',
            '-o',
            'remember_window_size=no',
            '-o',
            'font_size=12',
            '-o',
            'cursor=#ffff00',
            '-o',
            'cursor_blink_interval=0',
            '-o',
            f'background_opacity={opacity}',
            '-o',
            f'background_opacity_all_colors={"yes" if enabled else "no"}',
            '-o',
            f'transparent_background_colors={first}@0.8',
            sys.executable,
            str(Path(__file__).resolve()),
            '--fixture',
        ]
        if layers:
            command.append('--layers')
        with open(directory / (name + '.log'), 'w') as log:
            process = subprocess.Popen(command, cwd=root, stdout=log, stderr=log)
            try:
                rc = [str(launcher), '@', '--to', f'unix:{socket}']
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(f'kitty exited; see {log.name}')
                    result = subprocess.run(rc + ['ls'], capture_output=True, text=True)
                    if result.returncode == 0 and 'opacity-fixture-ready' in result.stdout:
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError('fixture did not become ready')
                time.sleep(0.5)
                subprocess.run(rc + ['screenshot', str(png)], check=True)
                image = Image.open(png).convert('RGBA')
                histogram = collections.Counter(image.getdata())
                for i, rgb in enumerate([*COLORS, REVERSED, INDEXED]):
                    alpha = opacity if enabled else (0.8 if i == 0 else 1.0)
                    # Transparent RGB cannot be recovered when alpha is zero.
                    if alpha == 0:
                        continue
                    expected = round(alpha * 255)
                    # The unscaled remote screenshot reads the final Wayland
                    # framebuffer directly: RGB is premultiplied sRGB.
                    premul_rgb = tuple(round(c * alpha) for c in rgb)
                    count = sum(
                        n for pixel, n in histogram.items() if max(abs(pixel[j] - premul_rgb[j]) for j in range(3)) <= 2 and abs(pixel[3] - expected) <= 1
                    )
                    assert count > 100, (name, rgb, expected, count)
                opaque_white = sum(n for (r, g, b, a), n in histogram.items() if min(r, g, b) >= 253 and a == 255)
                assert opaque_white > 100, (name, 'foreground lost opacity', opaque_white)
                if enabled and opacity < 1:
                    # Partial glyph coverage must retain intermediate alpha,
                    # not get the same opacity as either background or glyph core.
                    base_alpha = round(opacity * 255)
                    assert sum(n for (*_, a), n in histogram.items() if base_alpha + 2 < a < 253) > 100, (name, 'missing anti-aliasing')
                    assert sum(n for (*_, a), n in histogram.items() if abs(a - base_alpha) <= 1) > 1000
                if layers:
                    assert histogram[(0, 255, 0, 255)] > 100, (name, 'graphics opacity')
                    assert histogram[(255, 255, 0, 255)] > 20, (name, 'block cursor opacity')
                print(f'PASS {name}: 18 backgrounds, opaque glyph cores, RGBA coverage', flush=True)
                if enabled and opacity == 0.4 and not layers:
                    # Reload only our own window's config: no persistent changes.
                    subprocess.run(rc + ['load-config', '-o', 'background_opacity_all_colors=no'], check=True)
                    time.sleep(0.3)
                    reloaded = directory / 'reloaded-off.png'
                    subprocess.run(rc + ['screenshot', str(reloaded)], check=True)
                    pixels = collections.Counter(Image.open(reloaded).convert('RGBA').getdata())
                    assert pixels[(*COLORS[1], 255)] > 100, 'reload did not restore legacy opacity'
                    subprocess.run(rc + ['load-config', '-o', 'background_opacity_all_colors=yes'], check=True)
                    time.sleep(0.3)
                    reloaded = directory / 'reloaded-on.png'
                    subprocess.run(rc + ['screenshot', str(reloaded)], check=True)
                    pixels = collections.Counter(Image.open(reloaded).convert('RGBA').getdata())
                    rgb = tuple(round(c * opacity) for c in COLORS[1])
                    assert pixels[(*rgb, round(opacity * 255))] > 100, 'reload did not restore all-colors opacity'
                    print('PASS live config reload: on -> off -> on', flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    if '--fixture' in sys.argv:
        fixture()
    else:
        main()
