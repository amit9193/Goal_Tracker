from django.conf import settings
from django.db import models
from django.urls import reverse

QUARTERS = ("q1", "q2", "q3", "q4")


class Team(models.Model):
    COLORS = [("#0e9f6e", "Green"), ("#2563eb", "Blue"), ("#d97706", "Amber"), ("#7c3aed", "Violet"),
              ("#db2777", "Pink"), ("#0891b2", "Cyan"), ("#0b1f2e", "Ink")]
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, choices=COLORS, default="#0e9f6e")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="children", verbose_name="Parent team")
    lead = models.ForeignKey("TeamMember", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="leads", verbose_name="Team lead")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("team_detail", args=[self.pk])

    def descendants(self):
        out = []
        for c in self.children.all():
            out += [c] + c.descendants()
        return out


class TeamMember(models.Model):
    name = models.CharField(max_length=120, unique=True)
    role = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    joined = models.DateField(null=True, blank=True)
    manager = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports",
                                verbose_name="Reports to (Manager / Project Lead)")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="member", verbose_name="Login account")

    def subtree_ids(self):
        """IDs of this member and everyone reporting to them (recursively)."""
        ids, frontier = {self.pk}, [self.pk]
        while frontier:
            frontier = [i for i in TeamMember.objects.filter(manager_id__in=frontier).values_list("pk", flat=True) if i not in ids]
            ids.update(frontier)
        return ids

    @property
    def is_manager(self):
        return self.reports.exists() or self.led_goals.exists()

    def get_absolute_url(self):
        return reverse("member_detail", args=[self.pk])

    def goal_stats(self):
        mg = [g for g in self.goals.all() if g.title]
        return {"count": len(mg), "complete": sum(g.status == "Complete" for g in mg),
                "progress": round(sum(g.progress for g in mg) / len(mg)) if mg else 0}

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def initials(self):
        return "".join(w[0] for w in self.name.split()[:2]).upper()


class Goal(models.Model):
    STATUS_CHOICES = [
        ("Not Started", "Not Started"),
        ("On Track", "On Track"),
        ("Slow", "Slow"),
        ("At Risk", "At Risk"),
        ("Complete", "Complete"),
    ]
    project_lead = models.ForeignKey(TeamMember, on_delete=models.SET_NULL, related_name="led_goals",
                                     verbose_name="Project Lead", null=True, blank=True)
    goal_id = models.CharField("Goal ID", max_length=20, unique=True)
    member = models.ForeignKey(TeamMember, on_delete=models.CASCADE, related_name="goals",
                               verbose_name="Team Member", null=True, blank=True)
    role = models.CharField(max_length=120, blank=True)
    title = models.TextField("Goal", blank=True)
    description = models.TextField("Goal Description", blank=True)
    kpi = models.TextField("Success Measure / KPI", blank=True)
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    # Targets/actuals stored as percentage points (0-100), sheet stores fractions (0-1)
    q1_planned = models.DecimalField("Q1 Planned Target", max_digits=6, decimal_places=2, null=True, blank=True)
    q1_actual = models.DecimalField("Q1 Actual Achieved", max_digits=6, decimal_places=2, null=True, blank=True)
    q2_planned = models.DecimalField("Q2 Planned Target", max_digits=6, decimal_places=2, null=True, blank=True)
    q2_actual = models.DecimalField("Q2 Actual Achieved", max_digits=6, decimal_places=2, null=True, blank=True)
    q3_planned = models.DecimalField("Q3 Planned Target", max_digits=6, decimal_places=2, null=True, blank=True)
    q3_actual = models.DecimalField("Q3 Actual Achieved", max_digits=6, decimal_places=2, null=True, blank=True)
    q4_planned = models.DecimalField("Q4 Planned Target", max_digits=6, decimal_places=2, null=True, blank=True)
    q4_actual = models.DecimalField("Q4 Actual Achieved", max_digits=6, decimal_places=2, null=True, blank=True)
    status = models.CharField("Variance / Status", max_length=20, choices=STATUS_CHOICES, default="Not Started")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["goal_id"]

    def __str__(self):
        return f"{self.goal_id} — {(self.title or '')[:60]}"

    def get_absolute_url(self):
        return reverse("goal_detail", args=[self.pk])

    @property
    def is_defined(self):
        return bool(self.title)

    def quarter(self, q):
        """Mirrors sheet formulas: % = Actual/Planned, Variance = Planned - Actual."""
        planned = getattr(self, f"{q}_planned")
        actual = getattr(self, f"{q}_actual")
        pct = round(float(actual) / float(planned) * 100, 1) if planned and actual is not None else None
        variance = float(planned) - float(actual or 0) if planned is not None else None
        return {"q": q.upper(), "planned": planned, "actual": actual, "pct": pct, "variance": variance}

    @property
    def quarters(self):
        return [self.quarter(q) for q in QUARTERS]

    def _latest(self, kind):
        """Quarterly targets are cumulative in the sheet (Q1 25% -> Q2 50%), so use the latest filled quarter."""
        vals = [getattr(self, f"{q}_{kind}") for q in QUARTERS]
        vals = [float(v) for v in vals if v is not None]
        return vals[-1] if vals else 0.0

    @property
    def total_planned(self):
        return self._latest("planned")

    @property
    def total_actual(self):
        return self._latest("actual")

    @property
    def progress(self):
        """Overall progress: Complete = 100, else latest cumulative actual achieved (capped 100)."""
        if self.status == "Complete":
            return 100
        return min(round(self.total_actual), 100)

    @property
    def planned_progress(self):
        return min(round(self.total_planned), 100)

    @property
    def status_class(self):
        return {"Complete": "complete", "On Track": "ontrack", "Slow": "slow",
                "At Risk": "risk"}.get(self.status, "notstarted")


class CheckIn(models.Model):
    """Progress note / check-in against a goal."""
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="checkins")
    author = models.CharField(max_length=150)
    note = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]
