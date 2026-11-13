"""Excel test-paper template: build the blank/sample template and read a filled one back, pictures included.

Pictures can be pasted over a cell (normal Ctrl+V) or put in a cell with Excel's "Place in Cell"; both are read."""
import io
import re
import zipfile
from xml.etree import ElementTree as ET

import openpyxl
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

TYPES = {"single choice": "mcq", "multiple choice": "multi", "short answer": "short", "long answer": "long", "file upload": "file"}
TYPE_LABELS = ["Single choice", "Multiple choice", "Short answer", "Long answer", "File upload"]
LETTERS = "ABCDEF"

# Questions sheet columns (1-based)
COLS = ["Section", "Type", "Question", "Question picture"]
for L in LETTERS:
    COLS += [f"Option {L}", f"Option {L} picture"]
COLS += ["Correct answer(s)", "Points"]
C_SECTION, C_TYPE, C_QUESTION, C_QPIC = 1, 2, 3, 4
C_OPT = {L: 5 + 2 * i for i, L in enumerate(LETTERS)}      # text column
C_OPTPIC = {L: 6 + 2 * i for i, L in enumerate(LETTERS)}   # picture column
C_CORRECT, C_POINTS = 17, 18

DETAILS = [
    ("Test name", "Oracle General Ledger - Sample Test", "Shown to the candidate at the top of the test."),
    ("Department(s)", "ERP-EPM", "One or more department names, separated by commas, exactly as in HireModus."),
    ("Time limit (minutes)", 40, "The test submits itself when this runs out."),
    ("Instructions", "Answer every question. Multiple choice questions that say 'select all that apply' need every correct option and nothing else.", "Shown before the candidate starts."),
    ("Shuffle question order", "No", "Yes or No"),
    ("Shuffle answer options", "Yes", "Yes or No. Each candidate sees the options in a different order."),
    ("Choice questions per candidate", "", "Leave empty to give everyone every question. A number draws that many choice questions at random."),
    ("Written questions per candidate", "", "Same for short, long and file-upload questions."),
]

NAVY = "1B2A4A"
CORAL = "E5484D"
thin = Side(style="thin", color="D7DCE7")


# ---------------------------------------------------------------- sample pictures

def _png(draw_fn, size=(150, 110)) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    draw_fn(d, size)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _polygon(d, cx, cy, r, sides, fill):
    import math
    if sides == 0:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fill, width=4)
        return
    pts = [(cx + r * math.cos(math.pi * 2 * k / sides - math.pi / 2), cy + r * math.sin(math.pi * 2 * k / sides - math.pi / 2)) for k in range(sides)]
    d.polygon(pts, outline=fill, width=4)


def sample_pictures() -> dict[str, bytes]:
    def sequence(d, size):
        for i, sides in enumerate([3, 4, 5]):
            _polygon(d, 45 + i * 85, 55, 30, sides, "#1B2A4A")
        d.text((285, 42), "?", fill="#E5484D", font_size=34) if hasattr(d, "text") else None

    def one(sides):
        return lambda d, size: _polygon(d, size[0] // 2, size[1] // 2, 36, sides, "#1B2A4A")
    return {
        "question": _png(sequence, (340, 110)),
        "A": _png(one(6)), "B": _png(one(0)), "C": _png(one(4)), "D": _png(one(3)),
    }


# ---------------------------------------------------------------- template

def build_template(with_samples: bool = True) -> bytes:
    wb = openpyxl.Workbook()
    head_fill = PatternFill("solid", fgColor=NAVY)
    head_font = Font(bold=True, color="FFFFFF")

    # how-to sheet
    hw = wb.active
    hw.title = "How to use"
    lines = [
        ("HireModus test paper template", True),
        ("", False),
        ("1. Fill in the 'Test details' sheet: name, department(s), time limit and options.", False),
        ("2. Add one row per question on the 'Questions' sheet. Delete the sample rows you don't need.", False),
        ("3. Type: pick from the list: Single choice, Multiple choice, Short answer, Long answer, File upload.", False),
        ("4. Options: fill Option A, B, C... for choice questions (2 to 6 options). Leave them empty for written questions.", False),
        ("5. Correct answer(s): the letter for single choice (B), or every correct letter for multiple choice (A, C).", False),
        ("   Multiple choice only scores if the candidate picks exactly those options.", False),
        ("6. Points: how much the question is worth. Written answers are marked by the panel.", False),
        ("7. Pictures (aptitude questions): copy a picture and paste it (Ctrl+V) onto the picture cell of that row, so the", False),
        ("   picture's top-left corner sits inside that cell. Excel's 'Place in Cell' also works. An option can be text, a picture, or both.", False),
        ("8. Section is optional (for example Aptitude, Technical, HR). It is shown to the candidate above the question.", False),
        ("9. File upload questions let the candidate attach a file (used for the Dev team).", False),
        ("", False),
        ("Then in HireModus: Tests > Upload test paper. You'll see a preview with any problems listed by row before anything is saved,", False),
        ("and you can create a new test, add the questions to an existing test, or replace an existing test's questions.", False),
    ]
    for i, (text, bold) in enumerate(lines, 1):
        c = hw.cell(row=i, column=1, value=text)
        c.font = Font(bold=bold, size=14 if bold else 11, color=CORAL if bold else "1B2A4A")
    hw.column_dimensions["A"].width = 130

    # details sheet
    dw = wb.create_sheet("Test details")
    for col, (h, w) in enumerate([("Setting", 34), ("Value", 60), ("Help", 80)], 1):
        c = dw.cell(row=1, column=col, value=h)
        c.fill, c.font = head_fill, head_font
        dw.column_dimensions[get_column_letter(col)].width = w
    for r, (k, v, help_) in enumerate(DETAILS, 2):
        dw.cell(row=r, column=1, value=k).font = Font(bold=True)
        dw.cell(row=r, column=2, value=v if with_samples else ("" if k != "Time limit (minutes)" else 30))
        dw.cell(row=r, column=3, value=help_).font = Font(color="6B7690", italic=True)
        for col in (1, 2, 3):
            dw.cell(row=r, column=col).alignment = Alignment(wrap_text=True, vertical="top")
    yn = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    dw.add_data_validation(yn)
    yn.add("B6:B7")

    # questions sheet
    qw = wb.create_sheet("Questions")
    for col, h in enumerate(COLS, 1):
        c = qw.cell(row=1, column=col, value=h)
        c.fill = head_fill if "picture" not in h else PatternFill("solid", fgColor=CORAL)
        c.font = head_font
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        width = 14 if h in ("Section", "Type", "Points") else 46 if h == "Question" else 18 if "picture" in h else 22
        qw.column_dimensions[get_column_letter(col)].width = width
    qw.column_dimensions[get_column_letter(C_QPIC)].width = 40
    qw.row_dimensions[1].height = 34
    qw.freeze_panes = "D2"
    tv = DataValidation(type="list", formula1='"' + ",".join(TYPE_LABELS) + '"', allow_blank=True)
    qw.add_data_validation(tv)
    tv.add("B2:B500")

    if with_samples:
        samples = [
            ("Technical", "Single choice", "In Oracle Fusion General Ledger, which component defines the chart of accounts, calendar, currency and accounting method together?",
             {"A": "Business unit", "B": "Ledger", "C": "Legal entity", "D": "Data access set"}, "B", 1),
            ("Technical", "Multiple choice", "Which two determinant types are used in reference data assignment? (Select all that apply)",
             {"A": "Business Unit", "B": "Account Segment", "C": "Project Segment", "D": "Project Unit"}, "A, D", 2),
            ("Aptitude", "Single choice", "Which shape comes next in the sequence?", {"A": "", "B": "", "C": "", "D": ""}, "A", 1),
            ("Aptitude", "Single choice", "If 3 analysts complete 3 reports in 3 hours, how many reports do 6 analysts complete in 6 hours?",
             {"A": "6", "B": "9", "C": "12", "D": "18"}, "C", 1),
            ("Technical", "Short answer", "What is a Balance Forward Bill?", {}, "", 1),
            ("Technical", "Long answer", "Walk through the main steps to close a General Ledger period, and one issue you would expect during testing.", {}, "", 5),
            ("Technical", "File upload", "Upload your BI Publisher report output (PDF, Excel or a screenshot).", {}, "", 5),
        ]
        pics = sample_pictures()
        for r, (sec, typ, q, opts, corr, pts) in enumerate(samples, 2):
            qw.cell(row=r, column=C_SECTION, value=sec)
            qw.cell(row=r, column=C_TYPE, value=typ)
            qw.cell(row=r, column=C_QUESTION, value=q)
            for L, text in opts.items():
                qw.cell(row=r, column=C_OPT[L], value=text or None)
            qw.cell(row=r, column=C_CORRECT, value=corr or None)
            qw.cell(row=r, column=C_POINTS, value=pts)
            qw.row_dimensions[r].height = 34
            if sec == "Aptitude" and typ == "Single choice" and not any(opts.values()):
                qw.row_dimensions[r].height = 90
                qi = XLImage(io.BytesIO(pics["question"]))
                qi.width, qi.height = 250, 81
                qw.add_image(qi, f"{get_column_letter(C_QPIC)}{r}")
                for L in "ABCD":
                    oi = XLImage(io.BytesIO(pics[L]))
                    oi.width, oi.height = 110, 81
                    qw.add_image(oi, f"{get_column_letter(C_OPTPIC[L])}{r}")
    for row in qw.iter_rows(min_row=2, max_row=40, max_col=len(COLS)):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    wb.active = 2
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- reading a filled template

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
      "rv": "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata",
      "rvr": "http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel",
      "xlrd": "http://schemas.microsoft.com/office/spreadsheetml/2017/richdata"}


def _cell_ref(ref: str) -> tuple[int, int]:
    m = re.match(r"([A-Z]+)(\d+)", ref)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)), col


def in_cell_pictures(data: bytes, sheet_title: str) -> dict[tuple[int, int], tuple[bytes, str]]:
    """Pictures inserted with Excel's 'Place in Cell' (stored as rich values, invisible to openpyxl)."""
    out = {}
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
        if "xl/richData/rdrichvalue.xml" not in names or "xl/metadata.xml" not in names:
            return out
        # which sheet file holds the Questions sheet
        wbx = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid = next(s.get("{%s}id" % NS["r"]) for s in wbx.find("m:sheets", NS) if s.get("name") == sheet_title)
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        sheet_path = "xl/" + target.lstrip("/").replace("xl/", "") if not target.startswith("/xl/") else target.lstrip("/")
        # image list: richValueRel -> media
        rel_xml = ET.fromstring(z.read("xl/richData/richValueRel.xml"))
        rel_ids = [e.get("{%s}id" % NS["r"]) for e in rel_xml]
        rr = ET.fromstring(z.read("xl/richData/_rels/richValueRel.xml.rels"))
        rid_target = {r.get("Id"): r.get("Target") for r in rr}
        # rich values: first value is the image's relationship index (key _rvRel:LocalImageIdentifier)
        structs = []
        if "xl/richData/rdrichvaluestructure.xml" in names:
            st = ET.fromstring(z.read("xl/richData/rdrichvaluestructure.xml"))
            structs = [[k.get("n") for k in s] for s in st]
        rv = ET.fromstring(z.read("xl/richData/rdrichvalue.xml"))
        rv_img = []
        for v in rv:
            vals = [x.text for x in v]
            keys = structs[int(v.get("s", 0))] if structs else []
            idx = keys.index("_rvRel:LocalImageIdentifier") if "_rvRel:LocalImageIdentifier" in keys else 0
            rv_img.append(int(vals[idx]) if vals and vals[idx] is not None and vals[idx].isdigit() else None)
        # metadata: vm index -> rich value index
        md = ET.fromstring(z.read("xl/metadata.xml"))
        fut = []
        for fm in md.findall("m:futureMetadata", NS):
            for bk in fm.findall("m:bk", NS):
                rvb = bk.find(".//xlrd:rvb", NS)
                fut.append(int(rvb.get("i")) if rvb is not None else None)
        vm_to_rv = []
        vmeta = md.find("m:valueMetadata", NS)
        for bk in (vmeta if vmeta is not None else []):
            rc = bk.find("m:rc", NS)
            v = int(rc.get("v")) if rc is not None else 0
            vm_to_rv.append(fut[v] if v < len(fut) else None)
        sheet = ET.fromstring(z.read(sheet_path))
        for c in sheet.iter("{%s}c" % NS["m"]):
            vm = c.get("vm")
            if not vm:
                continue
            rvi = vm_to_rv[int(vm) - 1] if int(vm) - 1 < len(vm_to_rv) else None
            img_i = rv_img[rvi] if rvi is not None and rvi < len(rv_img) else None
            if img_i is None or img_i >= len(rel_ids):
                continue
            tgt = rid_target.get(rel_ids[img_i], "")
            path = "xl/" + tgt.replace("../", "")
            if path in names:
                out[_cell_ref(c.get("r"))] = (z.read(path), "." + path.rsplit(".", 1)[-1])
    except Exception:
        return out
    return out


def floating_pictures(ws) -> dict[tuple[int, int], tuple[bytes, str]]:
    out = {}
    for img in getattr(ws, "_images", []):
        try:
            anchor = img.anchor._from
            row, col = anchor.row + 1, anchor.col + 1
            data = img._data()
            fmt = (getattr(img, "format", "") or "png").lower()
            out.setdefault((row, col), (data, "." + ("jpg" if fmt == "jpeg" else fmt)))
        except Exception:
            continue
    return out


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_paper(data: bytes, save_image, departments: dict[str, int]) -> dict:
    """Returns {details, questions, errors, warnings}. save_image(bytes, ext) -> url."""
    errors, warnings = [], []
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception:
        return {"details": {}, "questions": [], "errors": ["This isn't a readable Excel file. Use the HireModus template (.xlsx)."], "warnings": [], "pictures": 0}
    if "Questions" not in wb.sheetnames:
        return {"details": {}, "questions": [], "errors": ["There's no 'Questions' sheet. Start from the HireModus template."], "warnings": [], "pictures": 0}

    details = {"name": "", "department_ids": [], "duration_min": 30, "instructions": "", "shuffle_questions": False,
               "shuffle_options": False, "pool_choice": None, "pool_written": None}
    if "Test details" in wb.sheetnames:
        dw = wb["Test details"]
        kv = {}
        for r in dw.iter_rows(min_row=2, max_col=2, values_only=True):
            if r[0]:
                kv[str(r[0]).strip().lower()] = r[1]
        details["name"] = _txt(kv.get("test name"))
        for name in [x.strip() for x in _txt(kv.get("department(s)")).split(",") if x.strip()]:
            if name.lower() in departments:
                details["department_ids"].append(departments[name.lower()])
            else:
                errors.append(f"Test details: department '{name}' doesn't exist in HireModus.")
        try:
            details["duration_min"] = int(float(kv.get("time limit (minutes)") or 30))
        except (TypeError, ValueError):
            errors.append("Test details: time limit must be a number of minutes.")
        details["instructions"] = _txt(kv.get("instructions"))
        details["shuffle_questions"] = _txt(kv.get("shuffle question order")).lower() == "yes"
        details["shuffle_options"] = _txt(kv.get("shuffle answer options")).lower() == "yes"
        for key, field in (("choice questions per candidate", "pool_choice"), ("written questions per candidate", "pool_written")):
            v = _txt(kv.get(key))
            if v:
                try:
                    details[field] = int(float(v))
                except ValueError:
                    errors.append(f"Test details: '{key}' must be a number or empty.")

    ws = wb["Questions"]
    pics = floating_pictures(ws)
    pics.update({k: v for k, v in in_cell_pictures(data, "Questions").items() if k not in pics})
    pic_urls = {}

    def pic(row, col):
        if (row, col) not in pics:
            return ""
        if (row, col) not in pic_urls:
            b, ext = pics[(row, col)]
            pic_urls[(row, col)] = save_image(b, ext)
        return pic_urls[(row, col)]

    questions = []
    for r in range(2, ws.max_row + 1):
        val = lambda col: _txt(ws.cell(row=r, column=col).value)
        typ_label, prompt = val(C_TYPE), val(C_QUESTION)
        has_any = typ_label or prompt or any((r, c) in pics for c in range(1, len(COLS) + 1))
        if not has_any:
            continue
        where = f"Row {r}"
        kind = TYPES.get(typ_label.lower())
        if not kind:
            errors.append(f"{where}: type '{typ_label or '(empty)'}' isn't one of: {', '.join(TYPE_LABELS)}.")
            continue
        qimg = pic(r, C_QPIC)
        if not prompt and not qimg:
            errors.append(f"{where}: the question is empty.")
            continue
        q = {"row": r, "section": val(C_SECTION), "kind": kind, "prompt": prompt or "(see picture)", "image": qimg,
             "options": [], "option_images": [], "correct_index": None, "correct_indices": [], "points": 1}
        pts = val(C_POINTS)
        if pts:
            try:
                q["points"] = float(pts)
            except ValueError:
                errors.append(f"{where}: points '{pts}' isn't a number.")
        if kind in ("mcq", "multi"):
            letters_used = []
            for L in LETTERS:
                text, img = val(C_OPT[L]), pic(r, C_OPTPIC[L])
                if text or img:
                    letters_used.append(L)
                    q["options"].append(text or f"Option {L}")
                    q["option_images"].append(img)
            if len(q["options"]) < 2:
                errors.append(f"{where}: a choice question needs at least two options (text or picture).")
                continue
            if letters_used != list(LETTERS[:len(letters_used)]):
                warnings.append(f"{where}: options skip a letter; they were renumbered in order.")
            raw = [x.strip().upper() for x in re.split(r"[,;/ ]+", val(C_CORRECT)) if x.strip()]
            idx = []
            for x in raw:
                if x in letters_used:
                    idx.append(letters_used.index(x))
                else:
                    errors.append(f"{where}: correct answer '{x}' isn't one of the filled options ({', '.join(letters_used)}).")
            if not idx:
                errors.append(f"{where}: give the correct answer letter(s).")
                continue
            if kind == "mcq":
                if len(idx) > 1:
                    errors.append(f"{where}: single choice has only one correct answer. Use 'Multiple choice' for more.")
                    continue
                q["correct_index"] = idx[0]
            else:
                q["correct_indices"] = sorted(set(idx))
        elif val(C_CORRECT):
            warnings.append(f"{where}: written questions are marked by the panel, so the correct answer column was ignored.")
        questions.append(q)
    if not questions and not errors:
        errors.append("No questions found on the Questions sheet.")
    return {"details": details, "questions": questions, "errors": errors, "warnings": warnings,
            "pictures": len(pic_urls)}
