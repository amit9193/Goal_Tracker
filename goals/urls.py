from django.urls import path

from django.views.generic import RedirectView

from . import views, views_team as vt

urlpatterns = [
    path("", views.landing, name="landing"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("goals/", views.goal_list, name="goal_list"),
    path("goals/new/", views.goal_form, name="goal_create"),
    path("goals/<int:pk>/", views.goal_detail, name="goal_detail"),
    path("goals/<int:pk>/edit/", views.goal_form, name="goal_edit"),
    path("goals/<int:pk>/delete/", views.goal_delete, name="goal_delete"),
    path("goals/<int:pk>/quick/", views.goal_quick_update, name="goal_quick"),
    path("goals/<int:pk>/unassign/", views.goal_unassign, name="goal_unassign"),
    path("goals/assign/", views.goal_assign, name="goal_assign"),
    # People
    path("team/", RedirectView.as_view(pattern_name="people")),
    path("people/", vt.people, name="people"),
    path("people/export/", vt.people_export, name="people_export"),
    path("people/assign/", vt.assign_team, name="assign_team"),
    path("people/<int:pk>/", vt.member_detail, name="member_detail"),
    path("people/<int:pk>/edit/", vt.member_edit, name="member_edit"),
    path("people/<int:pk>/delete/", vt.member_delete, name="member_delete"),
    path("org/", vt.org, name="org"),
    path("org/set-manager/", vt.set_manager, name="set_manager"),
    # Teams
    path("teams/", vt.teams, name="teams"),
    path("teams/<int:pk>/", vt.team_detail, name="team_detail"),
    path("teams/<int:pk>/edit/", vt.team_edit, name="team_edit"),
    path("teams/<int:pk>/delete/", vt.team_delete, name="team_delete"),
    # Data
    path("import/", views.import_view, name="import"),
    path("export/", views.export_view, name="export"),
]
