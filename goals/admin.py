from django.contrib import admin

from .models import CheckIn, Goal, Team, TeamMember


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "team", "email")
    list_filter = ("team",)
    search_fields = ("name", "role")


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("goal_id", "member", "role", "status", "start_date", "target_date")
    list_filter = ("status", "member")
    search_fields = ("goal_id", "title", "description")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "lead")


admin.site.register(CheckIn)
