# KPI Tracker — Goal Tracker (Django)

Enterprise goal-tracking web app built from `Goal_Tracker_version_1.xlsx`.

## Features
- **Landing page** — product overview, features, methodology, CTA
- **Dashboard** — KPI cards, Quarterly Planned vs Actual chart, status donut, team progress (achieved vs planned marker), past-target-date list
- **Goals Tracker** — exact sheet columns: Goal ID, Team Member, Role, Goal, Description, Success Measure/KPI, Start/Target Date, Q1–Q4 Planned / Actual / % Achievement, Variance/Status; search + filters
- **Goal detail** — progress ring, KPI checklist, per-quarter Planned, Actual, % Achievement and Variance
- **Create / Edit** goals with live % Achievement preview
- **Employee profile** — all of the employee's goals editable inline (status, Q1–Q4 planned & actual) with live % Achievement, highlighted unsaved changes, single "Save changes"; plus assign/new/edit/remove/delete
- **Employees** — expand any employee to Add (new or assign existing), Quick-update progress, Edit, Remove (unassign) or Delete goals; searchable list with team filter, add-employee modal, inline "move to team", bulk-select → add to team, CSV export, employee profile page
- **Teams & Org Tree** — nested teams (parent/sub-team), team lead, colour; collapsible org tree with members, or card view; "Not in a team" panel
- **Team detail** — stats, progress ring, members table, "Add Member" picker (multi-select), remove from team; team-scoped goals link
- **Team filters** on Dashboard and Goals Tracker (include sub-teams)
- **Check-ins** — progress notes timeline on each goal
- **Loaders** — top progress bar, page overlay spinner, button spinners on submit, chart skeleton shimmer
- **Excel import / export** in the same workbook layout (export keeps `% Achievement` formulas)
- Login-protected workspace + Django admin

## Roles & access (v1.1)
| Role | Who | Sees |
|---|---|---|
| Super User (Stage 1) | Django superuser | Everything; can import, manage teams, create logins |
| Manager / Project Lead (Stage 2) | Employee with reports or listed as Project Lead | Only their reporting tree's employees and goals (Dashboard, Goals, Employees, Org, Export) |
| Employee (Stage 3) | Employee login | Only their own goals |

- **Project Lead** column (first column in the sheet) is stored on each goal and sets the Team Member's manager.
- **Org Hierarchy** page: manager → team-member tree with per-node and Expand all / Collapse all buttons, search, bulk "Reports to" re-assignment (cycle-safe).
- Employee add/edit: Reports to, optional login username/password (Super Users).
- Excel export layout: `Project Lead | Goal ID | Team Member | … | Variance / Status`, plus `Formula` and `Hierarchy` sheets. Import accepts both new and old layouts.

## Formulas (from the sheet's "Formula" tab)
- `% Achievement = Actual Achieved / Planned Target`
- `Variance = Planned − Actual`
- Quarterly targets are cumulative (e.g. Q1 25% → Q2 50%); overall progress = latest quarter's actual (100% when status is Complete)
- Status values: Not Started · On Track · Slow · At Risk · Complete

## Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo     # imports data/Goal_Tracker_version_1_1.xlsx, demo teams, admin/admin123, employee logins first.last / Welcome@123
python manage.py runserver
```
Open http://127.0.0.1:8000 — sign in with **admin / admin123**.

## Tests
```bash
python manage.py test goals
```

## Structure
```
config/                 settings, root urls
goals/
  models.py             Team (hierarchy), TeamMember, Goal (+ formula logic), CheckIn
  excel.py              import/export matching the workbook layout
  views.py              dashboard, goals, check-ins, import/export
  views_team.py         employees, teams, org tree, assignment
  urls.py, forms.py, admin.py, tests.py
  management/commands/seed_demo.py
  templatetags/goal_tags.py
  templates/goals/      landing, dashboard, list, detail, form, team, import
  static/goals/         app.css (theme), chart.umd.min.js (Chart.js 4.4.1, bundled)
templates/              base.html, icons.html, registration/login.html
data/                   source Excel workbook
```
For production: set `DEBUG=False`, a new `SECRET_KEY`, `ALLOWED_HOSTS`, and run `collectstatic`.
