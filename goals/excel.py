"""Import/export matching the exact column layout of Goal_Tracker_version_1.xlsx."""
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Goal, TeamMember

HEADERS = ["Project Lead", "Goal ID", "Team Member", "Role", "Goal", "Goal Description", "Success Measure / KPI",
           "Start Date", "Target Date",
           "Q1 Planned Target", "Q1 Actual Achieved", "Q1 % Achievement",
           "Q2 Planned Target", "Q2 Actual Achieved", "Q2 % Achievement",
           "Q3 Planned Target", "Q3 Actual Achieved", "Q3% Achievement",
           "Q4 Planned Target", "Q4 Actual Achieved", "Q4 % Achievement",
           "Variance / Status"]
VALID_STATUS = {c[0] for c in Goal.STATUS_CHOICES}


def _pct(v):
    """Sheet stores 0.25 for 25%; app stores 25.00."""
    if v in (None, ""):
        return None
    v = float(v)
    return Decimal(str(round(v * 100 if v <= 1 else v, 2)))


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    return v or None


def import_workbook(file):
    wb = load_workbook(file, data_only=True)
    ws = wb["Goals Tracker"] if "Goals Tracker" in wb.sheetnames else wb.worksheets[0]
    created = updated = 0
    first = str(ws.cell(1, 1).value or "").strip().lower()
    has_lead = first == "project lead"
    for row in ws.iter_rows(min_row=2, values_only=True):
        row = list(row) + [None] * 22
        lead_name = str(row[0]).strip() if has_lead and row[0] else ""
        if has_lead:
            row = row[1:]
        gid = row[0]
        if not gid:
            continue
        member = None
        if row[1]:
            member, _ = TeamMember.objects.get_or_create(name=str(row[1]).strip())
            if row[2] and not member.role:
                member.role = row[2]
                member.save()
        lead = TeamMember.objects.get_or_create(name=lead_name)[0] if lead_name else None
        if lead and member and member != lead and member.manager_id != lead.pk and lead.pk not in member.subtree_ids():
            member.manager = lead
            member.save()
        status = (row[20] or "").strip() if row[20] else ""
        defaults = dict(
            project_lead=lead, member=member, role=row[2] or "", title=(row[3] or "").strip(),
            description=(row[4] or "").strip(), kpi=(row[5] or "").strip(),
            start_date=_date(row[6]), target_date=_date(row[7]),
            q1_planned=_pct(row[8]), q1_actual=_pct(row[9]),
            q2_planned=_pct(row[11]), q2_actual=_pct(row[12]),
            q3_planned=_pct(row[14]), q3_actual=_pct(row[15]),
            q4_planned=_pct(row[17]), q4_actual=_pct(row[18]),
            status=status if status in VALID_STATUS else "Not Started",
        )
        _, is_new = Goal.objects.update_or_create(goal_id=str(gid).strip(), defaults=defaults)
        created += is_new
        updated += not is_new
    if "Hierarchy" in wb.sheetnames:  # optional sheet from our export: Employee | Role | Reports To | Team
        for name, _role, boss, *_ in wb["Hierarchy"].iter_rows(min_row=2, values_only=True):
            if not name or not boss:
                continue
            m = TeamMember.objects.get_or_create(name=str(name).strip())[0]
            b = TeamMember.objects.get_or_create(name=str(boss).strip())[0]
            if m != b and b.pk not in m.subtree_ids():
                m.manager = b
                m.save()
    return created, updated


def export_workbook(goals):
    wb = Workbook()
    ws = wb.active
    ws.title = "Goals Tracker"
    ws.append(HEADERS)
    hdr = PatternFill("solid", fgColor="0F2A3D")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = hdr
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, g in enumerate(goals, start=2):
        f = lambda v: float(v) / 100 if v is not None else None
        ws.append([g.project_lead.name if g.project_lead else "", g.goal_id, g.member.name if g.member else "", g.role, g.title, g.description, g.kpi,
                   g.start_date, g.target_date,
                   f(g.q1_planned), f(g.q1_actual), f"=IFERROR(K{i}/J{i},\"\")",
                   f(g.q2_planned), f(g.q2_actual), f"=IFERROR(N{i}/M{i},\"\")",
                   f(g.q3_planned), f(g.q3_actual), f"=IFERROR(Q{i}/P{i},\"\")",
                   f(g.q4_planned), f(g.q4_actual), f"=IFERROR(T{i}/S{i},\"\")",
                   g.status])
        for col in (8, 9):
            ws.cell(i, col).number_format = "dd-mmm-yyyy"
        for col in range(10, 22):
            ws.cell(i, col).number_format = "0%"
    widths = [20, 9, 20, 22, 40, 50, 50, 13, 13] + [11] * 12 + [16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "D2"
    fs = wb.create_sheet("Formula")
    fs.append(["% Achievement", "Planned - Actual"])
    hs = wb.create_sheet("Hierarchy")
    hs.append(["Employee", "Role", "Reports To (Manager / Project Lead)", "Team"])
    for c in hs[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = hdr
    members = {g.member for g in goals if g.member} | {g.project_lead for g in goals if g.project_lead}
    for m in sorted(members, key=lambda x: x.name):
        hs.append([m.name, m.role, m.manager.name if m.manager else "", m.team.name if m.team else ""])
    for col, w in zip("ABCD", (24, 26, 34, 24)):
        hs.column_dimensions[col].width = w
    return wb
