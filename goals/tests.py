from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from .excel import export_workbook, import_workbook
from .models import Goal, Team, TeamMember

XLSX = Path(settings.BASE_DIR) / "data" / "Goal_Tracker_version_1_1.xlsx"


class GoalTrackerTests(TestCase):
    def setUp(self):
        import_workbook(XLSX)
        self.user = User.objects.create_superuser("u", "u@x.com", "p")
        self.client.login(username="u", password="p")

    def test_import_matches_sheet(self):
        self.assertEqual(Goal.objects.count(), 35)
        self.assertEqual(Goal.objects.exclude(title="").count(), 22)
        g = Goal.objects.get(goal_id="G-018")
        self.assertEqual(g.member.name, "Rajashekar Bayya")
        self.assertEqual(g.q1_planned, Decimal("25"))
        self.assertEqual(g.q2_planned, Decimal("50"))
        self.assertEqual(Goal.objects.get(goal_id="G-001").status, "Complete")

    def test_formulas(self):
        g = Goal.objects.get(goal_id="G-018")
        g.q2_actual = Decimal("40")
        q = g.quarter("q2")
        self.assertEqual(q["pct"], 80.0)       # Actual / Planned
        self.assertEqual(q["variance"], 10.0)  # Planned - Actual

    def test_pages(self):
        g = Goal.objects.first()
        for url in ["/", "/dashboard/", "/goals/", "/goals/?q=AI&status=On+Track", "/goals/new/",
                    f"/goals/{g.pk}/", f"/goals/{g.pk}/edit/", "/people/", "/import/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_create_and_export(self):
        m = TeamMember.objects.first()
        r = self.client.post("/goals/new/", {"goal_id": "G-900", "member": m.pk, "title": "Test", "status": "On Track",
                                             "q1_planned": "25", "q1_actual": "20"})
        self.assertEqual(r.status_code, 302)
        r = self.client.get("/export/")
        self.assertEqual(r.status_code, 200)
        buf = BytesIO(r.content)
        Goal.objects.all().delete()
        import_workbook(buf)  # round-trip
        self.assertEqual(Goal.objects.get(goal_id="G-900").q1_actual, Decimal("20"))

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/dashboard/").status_code, 302)


class TeamTests(TestCase):
    def setUp(self):
        import_workbook(XLSX)
        User.objects.create_superuser("u", "u@x.com", "p")
        self.client.login(username="u", password="p")
        self.root = Team.objects.create(name="Root")
        self.child = Team.objects.create(name="Child", parent=self.root)

    def test_pages(self):
        m = TeamMember.objects.first()
        for url in ["/people/", "/people/?unassigned=1", f"/people/{m.pk}/", f"/people/{m.pk}/edit/", "/people/export/",
                    "/teams/", "/teams/?view=cards", f"/teams/{self.root.pk}/", f"/teams/{self.root.pk}/edit/",
                    f"/dashboard/?team={self.root.pk}", f"/goals/?team={self.root.pk}"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_add_and_assign(self):
        r = self.client.post("/people/", {"name": "New Person", "role": "Dev", "team": self.child.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TeamMember.objects.get(name="New Person").team, self.child)
        ids = list(TeamMember.objects.values_list("pk", flat=True)[:3])
        self.client.post("/people/assign/", {"member": ids, "team": self.root.pk})
        self.assertEqual(TeamMember.objects.filter(team=self.root).count(), 3)
        # tree contains child under root and root-scoped goal filter includes child members
        r = self.client.get("/teams/")
        self.assertContains(r, "Child")

    def test_no_cycles(self):
        r = self.client.post(f"/teams/{self.root.pk}/edit/", {"name": "Root", "parent": self.child.pk, "color": "#0e9f6e"})
        self.assertEqual(r.status_code, 200)  # rejected
        self.root.refresh_from_db()
        self.assertIsNone(self.root.parent)

    def test_checkin(self):
        g = Goal.objects.exclude(title="").first()
        self.client.post(f"/goals/{g.pk}/", {"note": "Finished module 1"})
        self.assertEqual(g.checkins.count(), 1)


class EmployeeGoalTests(TestCase):
    def setUp(self):
        import_workbook(XLSX)
        User.objects.create_superuser("u", "u@x.com", "p")
        self.client.login(username="u", password="p")
        self.g = Goal.objects.get(goal_id="G-018")

    def test_quick_update(self):
        self.client.post(f"/goals/{self.g.pk}/quick/", {"status": "Slow", "q1_actual": "20", "next": "/people/"})
        self.g.refresh_from_db()
        self.assertEqual((self.g.status, self.g.q1_actual), ("Slow", Decimal("20")))

    def test_unassign_assign_delete(self):
        m = self.g.member
        r = self.client.post(f"/goals/{self.g.pk}/unassign/", {"next": "/people/"})
        self.assertRedirects(r, "/people/", fetch_redirect_response=False)
        self.g.refresh_from_db()
        self.assertIsNone(self.g.member)
        self.assertContains(self.client.get("/people/"), "Assign existing")
        self.client.post("/goals/assign/", {"member_id": m.pk, "goal": [self.g.pk]})
        self.g.refresh_from_db()
        self.assertEqual(self.g.member, m)
        self.client.post(f"/goals/{self.g.pk}/delete/", {"next": "/people/"})
        self.assertFalse(Goal.objects.filter(pk=self.g.pk).exists())

    def test_unsafe_next_ignored(self):
        r = self.client.post(f"/goals/{self.g.pk}/unassign/", {"next": "https://evil.com/"})
        self.assertEqual(r["Location"], "/goals/")

    def test_member_bulk_update(self):
        m = self.g.member
        r = self.client.post(f"/people/{m.pk}/", {f"{self.g.pk}-status": "Slow", f"{self.g.pk}-q1_actual": "20",
                                                   f"{self.g.pk}-q2_planned": "60", f"{self.g.pk}-q3_actual": "150"})
        self.assertEqual(r.status_code, 302)
        self.g.refresh_from_db()
        self.assertEqual((self.g.status, self.g.q1_actual, self.g.q2_planned, self.g.q3_actual),
                         ("Slow", Decimal("20"), Decimal("60"), None))  # 150 rejected
        self.assertContains(self.client.get(f"/people/{m.pk}/"), "Save changes")


class AccessTests(TestCase):
    """Project Lead sees only their team's records; employee sees only own."""
    def setUp(self):
        import_workbook(XLSX)
        self.amit = TeamMember.objects.get(name="Amit Ranawade")
        self.raj = TeamMember.objects.get(name="Rajashekar Bayya")
        # Second lead with own member to prove isolation
        self.other = TeamMember.objects.create(name="Other Lead")
        self.x = TeamMember.objects.create(name="X Person", manager=self.other)
        Goal.objects.create(goal_id="G-900", title="Other team goal", member=self.x, project_lead=self.other)
        self.amit.user = User.objects.create_user("amit", password="p"); self.amit.save()
        self.raj.user = User.objects.create_user("raj", password="p"); self.raj.save()
        self.other.user = User.objects.create_user("other", password="p"); self.other.save()

    def test_import_sets_lead_and_hierarchy(self):
        self.assertEqual(Goal.objects.get(goal_id="G-001").project_lead, self.amit)
        self.assertEqual(self.raj.manager, self.amit)

    def test_lead_sees_only_team(self):
        self.client.login(username="amit", password="p")
        r = self.client.get("/goals/?show=all")
        self.assertContains(r, "G-001")
        self.assertNotContains(r, "G-900")
        self.assertEqual(self.client.get(f"/goals/{Goal.objects.get(goal_id='G-900').pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/people/{self.x.pk}/").status_code, 404)
        self.assertNotContains(self.client.get("/people/"), "X Person")
        self.assertContains(self.client.get("/org/"), "Rajashekar Bayya")

    def test_other_lead_isolated(self):
        self.client.login(username="other", password="p")
        r = self.client.get("/goals/")
        self.assertContains(r, "G-900")
        self.assertNotContains(r, "G-001")

    def test_employee_sees_own_only(self):
        self.client.login(username="raj", password="p")
        r = self.client.get("/goals/")
        self.assertContains(r, "G-017")
        self.assertNotContains(r, "G-001")
        self.assertEqual(self.client.get("/import/").status_code, 302)  # super users only

    def test_export_new_format_roundtrip(self):
        self.client.login(username="amit", password="p")
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(self.client.get("/export/").content))
        ws = wb["Goals Tracker"]
        self.assertEqual(ws["A1"].value, "Project Lead")
        self.assertEqual(ws["L2"].value, '=IFERROR(K2/J2,"")')
        self.assertIn("Hierarchy", wb.sheetnames)
        ids = [c.value for c in ws["B"][1:]]
        self.assertIn("G-001", ids)
        self.assertNotIn("G-900", ids)

    def test_set_manager_no_cycle(self):
        self.client.login(username="amit", password="p")
        self.client.post("/org/set-manager/", {"manager": self.raj.pk, "member": [self.amit.pk]})
        self.amit.refresh_from_db()
        self.assertIsNone(self.amit.manager)  # cannot re-parent self / create a cycle

    def test_member_login_creation(self):
        su = User.objects.create_superuser("su", "s@x.com", "p")
        self.client.login(username="su", password="p")
        self.client.post("/people/", {"name": "New Emp", "manager": self.amit.pk, "username": "new.emp", "password": "Pass@123"})
        m = TeamMember.objects.get(name="New Emp")
        self.assertEqual((m.manager, m.user.username), (self.amit, "new.emp"))
        self.assertTrue(m.user.check_password("Pass@123"))
