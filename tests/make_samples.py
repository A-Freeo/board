"""Writes made-up study documents for the tests into a folder: python3 make_samples.py folder
lecture.pdf (10 pages on heat engines), reading.html (a long web page) and notes.txt."""
import sys
from pathlib import Path

PAGES = [
    ("Lecture 4: Heat Engines", ["Thermodynamics 101 (a made-up sample for tests)", "Professor Ada Gearwright"]),
    ("What a heat engine does", ["A heat engine turns heat into work.", "It takes heat from a hot reservoir,",
                                 "turns some into work and dumps the rest."]),
    ("The first law", ["Energy is conserved: Q = W + delta U.", "Heat in equals work out plus the change in internal energy."]),
    ("The second law", ["No engine turns all its heat into work.", "Some heat must always flow to the cold reservoir."]),
    ("Carnot efficiency", ["The best possible efficiency is 1 - Tc / Th.", "Temperatures are in kelvin."]),
    ("Worked example", ["Th = 600 K and Tc = 300 K.", "Carnot efficiency = 1 - 300 / 600 = 50 percent."]),
    ("Boilers", ["Fire-tube boilers pass hot gas through tubes in the water.", "Water-tube boilers pass water through tubes in the fire."]),
    ("The governor", ["James Watt's governor keeps the engine speed steady.", "Spinning balls lift and close the steam valve."]),
    ("Entropy", ["Entropy measures how spread out energy is.", "In a closed system it never goes down."]),
    ("Summary", ["Heat engines, the two laws, Carnot, boilers and governors.", "Read chapter 4 before the quiz."]),
]


def text(words):
    return words.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(pages):
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
               3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"}
    kids = []
    number = 5
    for title, lines in pages:
        drawing = "BT /F2 26 Tf 72 700 Td ({}) Tj ET\n".format(text(title))
        for i, line in enumerate(lines):
            drawing += "BT /F1 14 Tf 72 {} Td ({}) Tj ET\n".format(650 - 26 * i, text(line))
        stream = drawing.encode("latin-1")
        objects[number] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream"
        objects[number + 1] = ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {} 0 R "
                               "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>".format(number)).encode()
        kids.append(number + 1)
        number += 2
    objects[2] = "<< /Type /Pages /Kids [{}] /Count {} >>".format(" ".join("{} 0 R".format(k) for k in kids), len(kids)).encode()
    out = bytearray(b"%PDF-1.4\n")
    where = {}
    for n in sorted(objects):
        where[n] = len(out)
        out += b"%d 0 obj\n" % n + objects[n] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % number
    for n in range(1, number):
        out += b"%010d 00000 n \n" % where[n]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (number, xref)
    return bytes(out)



folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
(folder / "lecture.pdf").write_bytes(pdf(PAGES))
paragraphs = "".join("<h2>Part {0}</h2><p>{1}</p>".format(i, ("The steam age changed how factories ran. Mills moved from rivers to towns. " * 12) +
                     ("Part {} ends here.".format(i))) for i in range(1, 13))
(folder / "reading.html").write_text("<html><head><title>The Steam Age</title><script>alert(1)</script></head><body>"
                                     "<nav>Home | About</nav><article><h1>The Steam Age</h1>" + paragraphs +
                                     "<h2>Boilers in mills</h2><p>Mill boilers were fire-tube boilers.</p></article></body></html>")
(folder / "notes.txt").write_text("My own notes\n\nThe governor was invented by James Watt.\n\nAsk about entropy.")
