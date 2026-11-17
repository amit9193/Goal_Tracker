from django import forms

from .models import CheckIn, Goal, Team, TeamMember


class GoalForm(forms.ModelForm):
    def limit_to(self, members_qs):
        self.fields["member"].queryset = members_qs
        self.fields["project_lead"].queryset = members_qs

    class Meta:
        model = Goal
        fields = ["project_lead", "goal_id", "member", "role", "title", "description", "kpi", "start_date", "target_date",
                  "q1_planned", "q1_actual", "q2_planned", "q2_actual",
                  "q3_planned", "q3_actual", "q4_planned", "q4_actual", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "target_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "title": forms.Textarea(attrs={"rows": 2}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "kpi": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for name, f in self.fields.items():
            f.widget.attrs.setdefault("class", "input")
            if name.endswith(("_planned", "_actual")):
                f.widget.attrs.update({"min": 0, "max": 100, "step": "0.01", "placeholder": "%"})

    def clean(self):
        d = super().clean()
        if d.get("start_date") and d.get("target_date") and d["target_date"] < d["start_date"]:
            self.add_error("target_date", "Target date cannot be before start date.")
        return d


class _Styled:
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "input")


class MemberForm(_Styled, forms.ModelForm):
    class Meta:
        model = TeamMember
        fields = ["name", "role", "email", "team", "manager", "joined"]
        widgets = {"joined": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    username = forms.CharField(required=False, label="Login username", help_text="Leave blank for no login.")
    password = forms.CharField(required=False, label="Login password", widget=forms.PasswordInput(render_value=False),
                               help_text="Set or reset password (optional when editing).")

    def __init__(self, *a, user=None, **kw):
        super().__init__(*a, **kw)
        if self.instance.pk:
            excl = self.instance.subtree_ids()
            self.fields["manager"].queryset = self.fields["manager"].queryset.exclude(pk__in=excl)
            if self.instance.user:
                self.fields["username"].initial = self.instance.user.username
        if user is not None and not user.is_superuser:
            from .access import visible_members
            self.fields["manager"].queryset = visible_members(user, self.fields["manager"].queryset)
            self.fields["manager"].required = True
            del self.fields["username"], self.fields["password"]

    def clean_username(self):
        from django.contrib.auth import get_user_model
        u = (self.cleaned_data.get("username") or "").strip()
        other = get_user_model().objects.filter(username=u).first() if u else None
        if other:
            if other.is_superuser:
                raise forms.ValidationError("Username belongs to a super user.")
            mem = getattr(other, "member", None)
            if mem and mem.pk != self.instance.pk:
                raise forms.ValidationError("Username already linked to another employee.")
        return u

    def save(self, commit=True):
        from django.contrib.auth import get_user_model
        m = super().save(commit=commit)
        uname = self.cleaned_data.get("username")
        if commit and uname:
            User = get_user_model()
            u = m.user or User.objects.filter(username=uname).first() or User(username=uname)
            u.username, u.email = uname, m.email or u.email
            if self.cleaned_data.get("password"):
                u.set_password(self.cleaned_data["password"])
            elif not u.pk:
                u.set_unusable_password()
            u.save()
            if m.user_id != u.pk:
                m.user = u
                m.save(update_fields=["user"])
        return m


class TeamForm(_Styled, forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "description", "parent", "lead", "color"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_parent(self):
        p = self.cleaned_data.get("parent")
        if p and self.instance.pk and (p == self.instance or p in self.instance.descendants()):
            raise forms.ValidationError("A team cannot be nested under itself.")
        return p


class CheckInForm(_Styled, forms.ModelForm):
    class Meta:
        model = CheckIn
        fields = ["note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3, "placeholder": "Share progress, blockers or next steps…"})}


class ImportForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"accept": ".xlsx", "class": "input"}))
