from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from goals.excel import import_workbook
from goals.models import Team, TeamMember


class Command(BaseCommand):
    help = "Load data/Goal_Tracker_version_1_1.xlsx, demo teams, admin (admin/admin123) and a login per employee (first.last / Welcome@123)."

    def handle(self, *args, **opts):
        path = Path(settings.BASE_DIR) / "data" / "Goal_Tracker_version_1_1.xlsx"
        c, u = import_workbook(path)
        self.stdout.write(self.style.SUCCESS(f"Goals imported: {c} created, {u} updated"))
        # Demo org structure (edit freely in the UI)
        root, _ = Team.objects.get_or_create(name="Data & Analytics", defaults={"color": "#0b1f2e",
            "description": "BI, data engineering and delivery practice."})
        spec = {"Delivery Management": ("#d97706", ["Amit Ranawade"], "Amit Ranawade"),
                "BI Development": ("#2563eb", ["Nimesh Dhole", "Ajay Sutar", "Akshay Kongari", "Vedang Deshmukh", "Vishal More"], "Ajay Sutar"),
                "Full Stack Engineering": ("#0e9f6e", ["Rajashekar Bayya"], "Rajashekar Bayya")}
        for name, (color, members, lead) in spec.items():
            t, _ = Team.objects.get_or_create(name=name, defaults={"color": color, "parent": root})
            TeamMember.objects.filter(name__in=members, team__isnull=True).update(team=t)
            if not t.lead:
                t.lead = TeamMember.objects.filter(name=lead).first()
                t.save()
        if not root.lead:
            root.lead = TeamMember.objects.filter(name="Amit Ranawade").first()
            root.save()
        self.stdout.write(self.style.SUCCESS("Demo teams created"))
        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin123")
            self.stdout.write(self.style.SUCCESS("Superuser created: admin / admin123"))
        made = []
        for m in TeamMember.objects.filter(user__isnull=True):
            uname = ".".join(m.name.lower().split()[:1] + m.name.lower().split()[-1:]) if len(m.name.split()) > 1 else m.name.lower()
            if User.objects.filter(username=uname).exists():
                continue
            parts = m.name.split()
            u = User.objects.create_user(uname, password="Welcome@123", first_name=parts[0], last_name=" ".join(parts[1:]))
            m.user = u
            m.save(update_fields=["user"])
            made.append(uname)
        if made:
            self.stdout.write(self.style.SUCCESS(f"Employee logins (password Welcome@123): {', '.join(made)}"))
