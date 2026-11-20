#!/usr/bin/env python3
"""RangeCapture のアイコン (src/app.ico) を作る。

デザイン: 紫のグラデーションの角丸タイルに、白いファインダー風のカギ（キャプチャ範囲）と、
その中に浮かぶ切り取った画像（紫の枠付きカード）。
小さいサイズほど細部を省き、線を太くして、タスクバーでもはっきり見えるようにしている。

使い方: python3 tools/make_icon.py   （Pillow と numpy が必要）
"""
import io
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 8  # 縦横 8 倍で描いてから縮小する（アンチエイリアス）

PURPLE = (177, 155, 217)      # 枠線の色と同じ #B19BD9
GRAD_TOP = (190, 168, 236)    # タイル左上
GRAD_BOTTOM = (96, 66, 186)   # タイル右下
DEEP = (74, 48, 150)          # 影・絵の濃い色
WHITE = (255, 255, 255)


def lerp(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def rounded_mask(size, box, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def draw_icon(px):
    """px x px のアイコンを 1 枚描く。"""
    S = px * SS
    u = lambda v: v * S  # 0..1 の座標をピクセルへ

    # 細部の量（小さいほど簡略化）
    small = px <= 24
    medium = 24 < px <= 48

    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # --- タイル（斜めグラデーション + 上側のうっすらハイライト）---
    margin = 0.0 if px <= 32 else 0.035
    radius = 0.24 if small else 0.22
    tile_box = (u(margin), u(margin), u(1 - margin) - 1, u(1 - margin) - 1)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) / S
    t = np.clip((xx * 0.45 + yy * 0.55 - margin) / (1 - 2 * margin), 0, 1)
    grad = np.zeros((S, S, 4), np.float32)
    for c in range(3):
        grad[..., c] = GRAD_TOP[c] + (GRAD_BOTTOM[c] - GRAD_TOP[c]) * t
    # 上半分に柔らかい光
    glow = np.clip(1 - yy / 0.55, 0, 1) ** 2 * 0.10
    grad[..., :3] = grad[..., :3] * (1 - glow[..., None]) + 255 * glow[..., None]
    grad[..., 3] = 255
    tile = Image.fromarray(grad.astype(np.uint8), "RGBA")
    tile_mask = rounded_mask(S, tile_box, u(radius * (1 - 2 * margin)))
    img.paste(tile, (0, 0), tile_mask)

    d = ImageDraw.Draw(img)

    # --- ファインダー風のカギ（四隅）---
    if small:
        inset, arm, stroke = 0.17, 0.25, 0.115
    elif medium:
        inset, arm, stroke = 0.19, 0.22, 0.085
    else:
        inset, arm, stroke = 0.20, 0.20, 0.068
    lo, hi = inset, 1 - inset
    w = u(stroke)
    r = w / 2
    for cx, cy, sx, sy in ((lo, lo, 1, 1), (hi, lo, -1, 1), (lo, hi, 1, -1), (hi, hi, -1, -1)):
        x0, y0 = u(cx), u(cy)
        # 横の腕
        xa, xb = sorted((x0, x0 + sx * u(arm)))
        ya, yb = sorted((y0, y0 + sy * w))
        d.rounded_rectangle((xa, ya, xb, yb), radius=r, fill=WHITE)
        # 縦の腕
        xa, xb = sorted((x0, x0 + sx * w))
        ya, yb = sorted((y0, y0 + sy * u(arm)))
        d.rounded_rectangle((xa, ya, xb, yb), radius=r, fill=WHITE)

    # --- 切り取った画像（カード）---
    if small:
        # 小さいサイズは白い四角だけ（はっきり見えることを優先）
        cbox = tuple(u(v) for v in (0.355, 0.355, 0.645, 0.645))
        d.rounded_rectangle(cbox, radius=u(0.03), fill=WHITE)
        return img.resize((px, px), Image.LANCZOS)

    img = Image.alpha_composite(img, card_layer(S, medium))
    return img.resize((px, px), Image.LANCZOS)


def card_layer(S, medium):
    """白いフチの写真カードを、影付き・少し傾けて描いたレイヤー。
    ファインダーの中から右下へ少しはみ出し、「切り取って浮かせた」感じを出す。"""
    u = lambda v: v * S
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cw, ch = (0.42, 0.33) if not medium else (0.44, 0.35)
    cx, cy = 0.545, 0.555
    cbox = (u(cx - cw / 2), u(cy - ch / 2), u(cx + cw / 2), u(cy + ch / 2))
    crad = u(0.03)
    angle = 8 if not medium else 0  # 反時計回りに少し傾ける（48px 以下はにじむのでまっすぐ）

    # 影（右下にぼかして落とす）
    sh = Image.new("L", (S, S), 0)
    off = u(0.022)
    ImageDraw.Draw(sh).rounded_rectangle(
        (cbox[0] + off * 0.6, cbox[1] + off * 1.5, cbox[2] + off * 0.6, cbox[3] + off * 1.5),
        radius=crad, fill=170)
    sh = sh.rotate(angle, resample=Image.BICUBIC, center=(u(cx), u(cy)))
    sh = sh.filter(ImageFilter.GaussianBlur(u(0.03)))
    shadow = Image.new("RGBA", (S, S), DEEP + (0,))
    shadow.putalpha(sh)
    layer = Image.alpha_composite(layer, shadow)

    card = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle(cbox, radius=crad, fill=WHITE)  # 写真の白いフチ
    fw = u(0.034 if not medium else 0.045)
    inner = (cbox[0] + fw, cbox[1] + fw, cbox[2] - fw, cbox[3] - fw)
    ix0, iy0, ix1, iy1 = inner
    iw, ih = ix1 - ix0, iy1 - iy0
    # 絵: 淡い空 + 太陽 + 山
    pic = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pic)
    pd.rectangle(inner, fill=(232, 224, 250, 255))
    if not medium:
        sr = ih * 0.15
        scx, scy = ix0 + iw * 0.74, iy0 + ih * 0.33
        pd.ellipse((scx - sr, scy - sr, scx + sr, scy + sr), fill=(255, 196, 120, 255))
    pd.polygon([(ix0 - 1, iy1 + 1), (ix0 + iw * 0.32, iy0 + ih * 0.40),
                (ix0 + iw * 0.66, iy1 + 1)], fill=PURPLE + (255,))
    pd.polygon([(ix0 + iw * 0.34, iy1 + 1), (ix0 + iw * 0.66, iy0 + ih * 0.56),
                (ix1 + 1, iy0 + ih * 0.92), (ix1 + 1, iy1 + 1)], fill=GRAD_BOTTOM + (255,))
    clip = rounded_mask(S, inner, max(1, crad * 0.5))
    pic.putalpha(Image.composite(pic.getchannel("A"), Image.new("L", (S, S), 0), clip))
    card = Image.alpha_composite(card, pic)
    card = card.rotate(angle, resample=Image.BICUBIC, center=(u(cx), u(cy)))
    return Image.alpha_composite(layer, card)


def bmp_entry(im):
    """ICO 用の 32bpp BMP 形式（BITMAPINFOHEADER + BGRA ボトムアップ + AND マスク）。"""
    w, h = im.size
    a = np.array(im.convert("RGBA"))
    bgra = a[::-1, :, [2, 1, 0, 3]].tobytes()
    mask_stride = ((w + 31) // 32) * 4
    mask = bytearray(mask_stride * h)  # 全部 0（アルファで透過させる）
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(bgra) + len(mask), 0, 0, 0, 0)
    return header + bgra + bytes(mask)


def png_entry(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_ico(path, images):
    """256px だけ PNG、ほかは BMP で格納する（Windows で最も互換性の高い形）。"""
    datas = [png_entry(im) if im.size[0] >= 256 else bmp_entry(im) for im in images]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for im, data in zip(images, datas):
        w = im.size[0]
        out += struct.pack("<BBBBHHII", w % 256, w % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(out + b"".join(datas))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "src", "app.ico")
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    images = [draw_icon(s) for s in sizes]
    write_ico(out, images)
    print("wrote", os.path.normpath(out))
    if len(sys.argv) > 1:  # プレビュー画像の出力先
        preview(images, sizes, sys.argv[1])


def preview(images, sizes, path):
    """明るい/暗いタスクバー上での実寸と、4 倍拡大のプレビュー。"""
    W = 40 + sum(s + 24 for s in sizes)
    H = 2 * (256 + 40) + 2 * 300
    sheet = Image.new("RGBA", (max(W, 1400), H), (255, 255, 255, 255))
    y = 20
    for bg in ((243, 243, 243), (32, 32, 32)):
        ImageDraw.Draw(sheet).rectangle((0, y - 20, sheet.width, y + 256 + 20), fill=bg + (255,))
        x = 20
        for im, s in zip(images, sizes):
            sheet.alpha_composite(im, (x, y + 256 - s))
            x += s + 24
        y += 256 + 40
    for bg in ((243, 243, 243), (32, 32, 32)):
        ImageDraw.Draw(sheet).rectangle((0, y - 10, sheet.width, y + 290), fill=bg + (255,))
        x = 20
        for im, s in zip(images, sizes):
            if s in (16, 24, 32, 48):
                big = im.resize((s * 5, s * 5), Image.NEAREST)
                sheet.alpha_composite(big, (x, y))
                x += s * 5 + 30
        y += 300
    sheet.convert("RGB").save(path)
    print("preview", path)


if __name__ == "__main__":
    main()
