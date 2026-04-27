"""
ELD / Driver's Daily Log — PDF Generator v3
Uses the official form template (base64pdf.txt) as background via PyMuPDF,
overlaying all data: status path, remarks brackets, header fields, recap.
"""

import base64
import os
import math
from io import BytesIO
from datetime import datetime

import fitz  # PyMuPDF

# ── Locate the template PDF ────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_B64 = os.path.join(_HERE, "..", "..", "base64pdf.txt")


def _load_template_bytes() -> bytes:
    """Decode the base64 template PDF and return raw bytes."""
    path = os.path.normpath(_TEMPLATE_B64)
    with open(path, "r") as f:
        b64 = f.read().strip()
    return base64.b64decode(b64)


# ── Coordinate map (PyMuPDF top-left origin, y increases downward) ─────────────
# Measured from the template via get_text / get_drawings inspection.

PAGE_W = 612.0
PAGE_H = 792.0

# ── Main grid ──
GRID_X0 = 100.23    # left edge of the 24-hour grid
GRID_X1 = 515.59   # right edge of the 24-hour grid
GRID_W  = GRID_X1 - GRID_X0   # 465.36 pt

# Dark header ruler band
RULER_TOP = 176.52
RULER_BOT = 200.60
RULER_H   = RULER_BOT - RULER_TOP   # 31.08 pt

# 4 status rows (below the dark ruler)
GRID_TOP  = RULER_BOT           # 207.60
ROW_H     = 22.77               # each row height
GRID_BOT  = GRID_TOP + 4 * ROW_H  # 298.68

# Bottom ruler of the main grid
BOT_RULER_TOP = GRID_BOT         # 298.68
BOT_RULER_BOT = 337.70

# Remarks zone
REMARKS_RULER_TOP = BOT_RULER_TOP
REMARKS_RULER_BOT = BOT_RULER_BOT
REMARKS_TEXT_TOP  = REMARKS_RULER_BOT   # 316.70
REMARKS_TEXT_BOT  = 456.6               # "Enter name of place..." text baseline

# Status row midpoints (y = center of each row, for drawing the horizontal lines)
def _row_mid(row_idx: int) -> float:
    """Center y of a status row (0=Off Duty … 3=On Duty) with manual offsets."""
    base_y = GRID_TOP + (row_idx + 0.5) * ROW_H
    if row_idx == 0:   # 1. Off Duty
        return base_y + 8.0  # Move down
    elif row_idx == 1: # 2. Sleeper Berth
        return base_y + 3.0  # Move down
    elif row_idx == 2: # 3. Driving
        return base_y - 1.5  # Move up
    elif row_idx == 3: # 4. On Duty
        return base_y - 5.0  # Move up
    return base_y

STATUS_ROW = {1: 0, 2: 1, 3: 2, 4: 3}   # status id -> row index

# Hour→x mapping
def hx(h_frac: float) -> float:
    """Fractional hour [0-24] → x position in PyMuPDF coordinates."""
    return GRID_X0 + (h_frac / 24.0) * GRID_W


# ── Text coordinate map for header fields ─────────────────────────────────────
# All y values are baselines in PyMuPDF (top-left origin).
# Fields are placed just above or below existing label text.

FIELD_COORDS = {
    # (x, y)  — y is where we INSERT the text (PyMuPDF baseline)
    "date_mo":   (220.5, 133.5),
    "date_da":   (268.3, 133.5),
    "date_yr":   (315.0, 133.5),
    "from_loc":  (140.0, 165.0),
    "to_loc":    (335.0, 165.0),
    # Vehicle / carrier block (below the "Name of Carrier" label at y=599.9)
    "carrier":     (359.0, 614.0),
    "truck_no":    (119.0, 667.0),
    "shipper_doc": (56.0, 410.0),
    "shipper_com": (56.0, 438.0),
    # Recap (Blue boxes at top of recap columns)
    "recap_on_duty":  (110.0, 510.0),
    "recap_avail_70": (245.0, 510.0),
    # Odometer / mileage
    "miles_driving":  (100.0, 600.0),
    "miles_total":    (190.0, 600.0),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def t_frac(iso: str, date_str: str) -> float:
    """ISO datetime → fractional hour (0-24) for the given date."""
    dt = datetime.fromisoformat(iso)
    if iso[:10] != date_str:
        return 24.0 if iso[:10] > date_str else 0.0
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def mins_hhmm(mins: int) -> str:
    h = mins // 60
    m = (mins % 60 // 15) * 15
    return f"{h}:{m:02d}"


_ACTION_ABBR = {
    "Pre-Trip Inspection":  "Pre-trip/TIV",
    "Post-Trip Inspection": "Post-trip/TIV",
    "Loading Freight":      "Pickup (1 hr)",
    "Unloading Freight":    "Dropoff (1 hr)",
    "Fueling":              "Fuel stop",
    "30 Min Break":         "30 min break",
    "Sleeper Berth":        "10 hr rest",
}


def _abbreviate_action(action: str) -> str:
    for key, abbr in _ACTION_ABBR.items():
        if action.startswith(key):
            return abbr
    return action


# ── Color helpers ─────────────────────────────────────────────────────────────

BLACK = (0, 0, 0)
RED   = (0.85, 0.05, 0.05)


# ── Main generator ────────────────────────────────────────────────────────────

class ELDPdfGenerator:
    """
    Generates a multi-page Driver's Daily Log PDF by overlaying data
    on top of the official template form (decoded from base64pdf.txt).
    """

    def __init__(self, driver_info: dict, logs_by_day: dict, route: dict):
        self.info  = driver_info
        self.logs  = logs_by_day
        self.route = route

    def generate(self) -> bytes:
        template_bytes = _load_template_bytes()
        out_buf = BytesIO()

        # Build one PDF per day, then concatenate
        output_doc = fitz.open()

        # Initialize cycle minutes from driver info (initial cycle used)
        initial_cycle_hrs = self.info.get("cycle_used_hrs", 0)
        running_cycle_mins = int(float(initial_cycle_hrs) * 60)

        for date_str in sorted(self.logs):
            # Open a fresh copy of the template for this page
            tmpl = fitz.open(stream=template_bytes, filetype="pdf")
            page = tmpl[0]
            day_evs = self.logs[date_str]

            # Calculate on-duty time for today to update the cycle
            today_on_duty = sum(ev.get("duration_mins", 0) for ev in day_evs if ev["status"] in (3, 4))
            running_cycle_mins += today_on_duty

            # Draw all overlays onto this page
            self._draw_header(page, date_str, day_evs)
            self._draw_status_path(page, day_evs, date_str)
            self._draw_remarks(page, self.logs[date_str], date_str)
            self._draw_recap(page, self.logs[date_str], running_cycle_mins)
            self._draw_shipping(page)

            # Insert the completed page into the output document
            output_doc.insert_pdf(tmpl, from_page=0, to_page=0)
            tmpl.close()

        output_doc.save(out_buf)
        output_doc.close()
        return out_buf.getvalue()

    # ── Header fields ─────────────────────────────────────────────────────────

    def _draw_header(self, page: fitz.Page, date_str: str, day_events: list):
        """Fill date, driver name, from/to, and daily mileage."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            mo = dt.strftime("%m")
            da = dt.strftime("%d")
            yr = dt.strftime("%Y")
        except Exception:
            mo = da = yr = "____"

        # Calculate daily mileage from events
        daily_km = sum(ev.get("distance_km", 0.0) for ev in day_events)
        daily_miles = round(daily_km * 0.621371, 1)

        def ins(key: str, text: str, size: float = 8, bold: bool = False):
            if key not in FIELD_COORDS:
                return
            x, y = FIELD_COORDS[key]
            font = "helv" if not bold else "hebo"
            page.insert_text(
                fitz.Point(x, y), text,
                fontsize=size, fontname=font, color=BLACK
            )

        ins("date_mo", mo, size=9, bold=True)
        ins("date_da", da, size=9, bold=True)
        ins("date_yr", yr, size=9, bold=True)

        truck = self.info.get("truck_no", "")
        if truck:
            page.insert_text(fitz.Point(100.0, 640.0), f"{truck}",
                             fontsize=7, fontname="helv", color=BLACK)

        from_loc = self.info.get("from_loc", "")
        if from_loc:
            ins("from_loc", from_loc, size=7)

        to_loc = self.info.get("to_loc", "")
        if to_loc:
            ins("to_loc", to_loc, size=7)

        carrier = self.info.get("carrier", "")
        if carrier:
            page.insert_text(fitz.Point(279.0, 595.0), carrier,
                             fontsize=7, fontname="helv", color=BLACK)

        trailer = self.info.get("trailer_no", "")
        home_t  = self.info.get("home_terminal", "")
        if trailer or home_t:
            page.insert_text(fitz.Point(180.0, 640.0),
                             f"{trailer}  /  {home_t}",
                             fontsize=7, fontname="helv", color=BLACK)

        # Mileage fields (Daily)
        if daily_miles > 0:
            ins("miles_driving", str(daily_miles), size=7)
            ins("miles_total",   str(daily_miles), size=7)

    # ── Status path ───────────────────────────────────────────────────────────

    def _draw_status_path(self, page: fitz.Page, events: list, date_str: str):
        """Draw the HOS line graph and red dots on the grid."""
        evs = sorted(events, key=lambda e: e["start"])
        if not evs:
            return

        shape = page.new_shape()

        # ── Build the step-line path segment by segment ────────────────────
        prev_y = None
        for ev in evs:
            row = STATUS_ROW.get(ev["status"], 0)
            ry  = _row_mid(row)
            xs  = hx(max(0.0, min(24.0, t_frac(ev["start"], date_str))))
            xe  = hx(max(0.0, min(24.0, t_frac(ev["end"],   date_str))))

            if prev_y is not None and prev_y != ry:
                # Vertical transition line (status change)
                shape.draw_line(fitz.Point(xs, prev_y), fitz.Point(xs, ry))

            # Horizontal segment for this status
            shape.draw_line(fitz.Point(xs, ry), fitz.Point(xe, ry))
            prev_y = ry

        shape.finish(color=BLACK, fill=None, width=1.5, closePath=False)
        shape.commit()

        # ── Total hours per row ──
        totals_x = GRID_X1 + 15  # just right of the grid
        for sid in (1, 2, 3, 4):
            row = STATUS_ROW[sid]
            ry  = _row_mid(row)
            tot = sum(e["duration_mins"] for e in events if e["status"] == sid)
            page.insert_text(
                fitz.Point(totals_x, ry + 3),
                mins_hhmm(tot),
                fontsize=7, fontname="hebo", color=BLACK
            )

        # ── Grand Total (24:00) ──
        # Sum of all durations should always be 24:00 (1440 mins)
        grand_total = sum(e["duration_mins"] for e in events)
        # Position it aligned with the remarks ruler baseline
        page.insert_text(
            fitz.Point(totals_x, REMARKS_RULER_BOT - 5.0),
            mins_hhmm(grand_total),
            fontsize=7, fontname="hebo", color=BLACK
        )

    # ── Remarks ───────────────────────────────────────────────────────────────

    def _draw_remarks(self, page: fitz.Page, events: list, date_str: str):
        """
        Draw remarks brackets for each significant stop.

        For each event:
          1. Short vertical line drops from the bottom of the remarks ruler
             down ~12 pt.
          2. A small horizontal "cap" (the bracket top) ±5pt wide.
          3. A diagonal line at -65° starting from the cap, going down-right.
          4. Text written along / beside the diagonal, in two lines:
             - Line 1 (bold): location name
             - Line 2 (regular): action abbreviation
        """
        # Collect significant events (skip Driving and generic Off Duty)
        key_evs = []
        seen = set()
        for ev in sorted(events, key=lambda e: e["start"]):
            act = ev.get("action", "")
            if act.startswith("Driving") or act == "Off Duty":
                continue
            key = (ev["start"][:16], act)
            if key not in seen and act:
                seen.add(key)
                key_evs.append(ev)

        # Geometry constants
        VERT_DROP   = 12.0     # short vertical from ruler bottom
        DIAG_LEN    = 75.0     # length of the diagonal bracket line
        ANGLE_DEG   = -45.0    # angle of diagonal (downward to the right)
        ANGLE_RAD   = math.radians(ANGLE_DEG)
        CAP_W       = 5.0      # half-width of horizontal cap tick
        TEXT_OFFSET = 3.0      # pixels offset from diagonal line to text baseline

        shape = page.new_shape()

        for ev in key_evs:
            frac_start = t_frac(ev["start"], date_str)
            frac_end   = t_frac(ev["end"], date_str)
            if not (0.0 <= frac_start <= 24.0):
                continue

            x_start = hx(frac_start)
            x_end   = hx(frac_end) if (0.0 <= frac_end <= 24.0) else x_start
            
            loc = ev.get("location", "")
            act = ev.get("action", "")

            # ── 1. Bracket logic ──────────────────────────────────────────
            vert_top = REMARKS_RULER_BOT
            vert_bot = vert_top + VERT_DROP

            if x_end - x_start > 2.0:
                # Interval event: draw a V-bracket
                mid_x = (x_start + x_end) / 2.0
                v_bot = vert_bot 
                
                # Left drop
                shape.draw_line(fitz.Point(x_start, vert_top), fitz.Point(x_start, vert_bot))
                shape.draw_line(fitz.Point(x_start, vert_bot), fitz.Point(mid_x, v_bot))
                
                # Right drop
                shape.draw_line(fitz.Point(x_end, vert_top), fitz.Point(x_end, vert_bot))
                shape.draw_line(fitz.Point(x_end, vert_bot), fitz.Point(mid_x, v_bot))
                
                diag_start = fitz.Point(mid_x, v_bot)
            else:
                # Point event: single drop
                shape.draw_line(fitz.Point(x_start, vert_top), fitz.Point(x_start, vert_bot))
                diag_start = fitz.Point(x_start, vert_bot)

            # ── 2. Diagonal bracket line going down-right at ANGLE_DEG ──────
            dx = DIAG_LEN * math.cos(ANGLE_RAD)
            dy = -DIAG_LEN * math.sin(ANGLE_RAD)   # positive = downward

            diag_end = fitz.Point(diag_start.x + dx, diag_start.y + dy)

            shape.draw_line(diag_start, diag_end)
            shape.finish(color=BLACK, width=0.9, closePath=False)

            # ── 5. Text labels along the diagonal ──────────────────────────
            label1 = loc if loc else _abbreviate_action(act)
            label2 = _abbreviate_action(act) if (loc and act) else ""

            # Move text 8pt down the line, and 4pt to the right of the line (perpendicular)
            along_x = 8 * math.cos(ANGLE_RAD)
            along_y = 8 * (-math.sin(ANGLE_RAD))
            perp_x = 5.3 * math.sin(ANGLE_RAD)
            perp_y = 5.3 * math.cos(ANGLE_RAD)
            
            text_start = fitz.Point(
                diag_start.x + along_x + perp_x,
                diag_start.y + along_y + perp_y,
            )

            # PyMuPDF insert_text only accepts rotate ∈ {0,90,180,270}.
            # For arbitrary diagonal text we use morph=(pivot, matrix).
            # Rotation matrix for ANGLE_DEG counterclockwise:
            cos_a = math.cos(ANGLE_RAD)
            sin_a = math.sin(ANGLE_RAD)
            rot_mat = fitz.Matrix(cos_a, sin_a, -sin_a, cos_a, 0, 0)

            page.insert_text(
                text_start, label1,
                fontsize=6.5, fontname="hebo", color=BLACK,
                morph=(text_start, rot_mat),
            )
            if label2 and label2 != label1:
                # Offset second line further perpendicular to the diagonal
                off_x = -7 * math.sin(ANGLE_RAD)
                off_y = -7 * math.cos(ANGLE_RAD)
                text2_pt = fitz.Point(text_start.x + off_x, text_start.y + off_y)
                page.insert_text(
                    text2_pt, label2,
                    fontsize=5.5, fontname="helv", color=BLACK,
                    morph=(text2_pt, rot_mat),
                )

        shape.commit()

    # ── Recap ─────────────────────────────────────────────────────────────────

    def _draw_recap(self, page: fitz.Page, events: list, running_cycle_mins: int):
        """Fill the 70hr/8day recap section with cumulative calculation."""
        # On duty today
        on_duty_today = sum(e["duration_mins"] for e in events if e["status"] in (3, 4))
        
        # Available tomorrow = 70 hrs (4200 min) - Total used in the cycle so far
        avail_tomorrow = max(0, 4200 - running_cycle_mins)

        if "recap_on_duty" in FIELD_COORDS:
            x, y = FIELD_COORDS["recap_on_duty"]
            page.insert_text(fitz.Point(x, y), mins_hhmm(on_duty_today),
                             fontsize=7, fontname="hebo", color=BLACK)
                             
        if "recap_avail_70" in FIELD_COORDS:
            x, y = FIELD_COORDS["recap_avail_70"]
            page.insert_text(fitz.Point(x, y), mins_hhmm(avail_tomorrow),
                             fontsize=7, fontname="hebo", color=BLACK)

    # ── Shipping docs ─────────────────────────────────────────────────────────

    def _draw_shipping(self, page: fitz.Page):
        """Fill shipping document fields."""
        doc_no = self.info.get("shipping_doc", "")
        shpr   = self.info.get("shipper_commodity", "")

        if doc_no and "shipper_doc" in FIELD_COORDS:
            x, y = FIELD_COORDS["shipper_doc"]
            page.insert_text(fitz.Point(x, y), doc_no,
                             fontsize=7, fontname="helv", color=BLACK)
                             
        if shpr and "shipper_com" in FIELD_COORDS:
            x, y = FIELD_COORDS["shipper_com"]
            page.insert_text(fitz.Point(x, y), shpr,
                             fontsize=7, fontname="helv", color=BLACK)
