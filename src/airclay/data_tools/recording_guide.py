"""Mandatory, click-through recording instructions, sourced from data/README.md."""
import re

from airclay.config import ROOT


WINDOW = "AirClay - Before recording"
WIDTH, HEIGHT = 960, 700
BACK = (44, 622, 164, 670)
NEXT = (716, 622, 916, 670)
BODY_WIDTH = 872


def guide_pages():
    """Wrap the README into pages; CLI launch instructions are README-only."""
    import cv2
    document = (ROOT / "data/README.md").read_text()
    pages = []
    for section in re.split(r"(?m)^## ", document)[1:]:
        title, _, body = section.partition("\n")
        if title.strip() == "Start recording":
            continue
        lines = []
        for paragraph in re.split(r"\n\s*\n", body.strip()):
            line = ""
            for word in paragraph.replace("**", "").replace("`", "").split():
                candidate = f"{line} {word}".strip()
                if line and cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, .56, 1)[0][0] > BODY_WIDTH:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            if line:
                lines.extend((line, ""))
        while lines and not lines[-1]:
            lines.pop()
        while lines:
            chunk, lines = lines[:18], lines[18:]
            pages.append((title.strip(), chunk))
    if not pages:
        raise RuntimeError("Recording instructions are empty: data/README.md")
    return pages


def guide_image(pages, index, cfg, args):
    import cv2
    import numpy as np
    canvas = np.full((HEIGHT, WIDTH, 3), (24, 27, 32), dtype=np.uint8)

    def text(value, x, y, size=.56, color=(225, 229, 235)):
        cv2.putText(canvas, value, (x, y), cv2.FONT_HERSHEY_SIMPLEX, size, color, 1, cv2.LINE_AA)

    text("AIRCLAY / RECORDING GUIDE", 44, 38, .48, (174, 187, 200))
    title, lines = pages[index]
    text(title, 44, 84, .82)
    text(f"Dominant hand: {cfg['dominant']}  |  " +
         (f"{args.repetitions} rounds  |  {getattr(args, 'prepare_seconds', 5):g}s preparation" if args.guided else "Free recording"),
         44, 115, .47, (174, 187, 200))
    for row, line in enumerate(lines):
        text(line, 44, 160 + row * 24)
    cv2.line(canvas, (44, 602), (916, 602), (66, 72, 82), 1)
    if index:
        cv2.rectangle(canvas, BACK[:2], BACK[2:], (57, 64, 75), -1)
        text("Back", 80, 653, .57)
    cv2.rectangle(canvas, NEXT[:2], NEXT[2:], (154, 207, 141), -1)
    label = "Continue" if index == len(pages) - 1 else "Next"
    text(label, 762 if label == "Continue" else 792, 653, .64, (24, 27, 32))
    text(f"{index + 1} / {len(pages)}", 458, 650, .52, (174, 187, 200))
    return canvas


def show_recording_guide(args, cfg):
    """Return True only after the final Continue button is clicked."""
    import cv2
    pages = guide_pages()
    index, proceed = 0, False

    def clicked(event, x, y, flags, userdata):
        nonlocal index, proceed
        if event != cv2.EVENT_LBUTTONUP:
            return
        if NEXT[0] <= x <= NEXT[2] and NEXT[1] <= y <= NEXT[3]:
            if index == len(pages) - 1:
                proceed = True
            else:
                index += 1
        elif index and BACK[0] <= x <= BACK[2] and BACK[1] <= y <= BACK[3]:
            index -= 1

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, clicked)
    try:
        while not proceed:
            cv2.imshow(WINDOW, guide_image(pages, index, cfg, args))
            key = cv2.waitKey(30) & 0xff
            if key in (ord("q"), ord("Q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return False
        return True
    finally:
        cv2.destroyWindow(WINDOW)
