app_name = "sas_forcex_fleeto"
app_title = "ForceX FLEETO"
app_publisher = "SAS Infosystem Pvt Ltd"
app_description = "FLEETO service & warranty module for ForceX"
app_email = "subhapriyo.banerjee@sasinfosystem.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext", "sas_forcex"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "sas_forcex_fleeto",
# 		"logo": "/assets/sas_forcex_fleeto/logo.png",
# 		"title": "ForceX FLEETO",
# 		"route": "/sas_forcex_fleeto",
# 		"has_permission": "sas_forcex_fleeto.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `sas_forcex_fleeto/dock/sas_forcex_fleeto/sas_forcex_fleeto.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/sas_forcex_fleeto/css/sas_forcex_fleeto.css"
# app_include_js = "/assets/sas_forcex_fleeto/js/sas_forcex_fleeto.js"

# include js, css files in header of web template
# web_include_css = "/assets/sas_forcex_fleeto/css/sas_forcex_fleeto.css"
# web_include_js = "/assets/sas_forcex_fleeto/js/sas_forcex_fleeto.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "sas_forcex_fleeto/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "sas_forcex_fleeto/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "sas_forcex_fleeto.utils.jinja_methods",
# 	"filters": "sas_forcex_fleeto.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "sas_forcex_fleeto.install.before_install"
# after_install = "sas_forcex_fleeto.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "sas_forcex_fleeto.uninstall.before_uninstall"
# after_uninstall = "sas_forcex_fleeto.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "sas_forcex_fleeto.utils.before_app_install"
# after_app_install = "sas_forcex_fleeto.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "sas_forcex_fleeto.utils.before_app_uninstall"
# after_app_uninstall = "sas_forcex_fleeto.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "sas_forcex_fleeto.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "sas_forcex_fleeto.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "sas_forcex_fleeto.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["sas_forcex_fleeto.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"sas_forcex_fleeto.tasks.all"
# 	],
# 	"daily": [
# 		"sas_forcex_fleeto.tasks.daily"
# 	],
# 	"hourly": [
# 		"sas_forcex_fleeto.tasks.hourly"
# 	],
# 	"weekly": [
# 		"sas_forcex_fleeto.tasks.weekly"
# 	],
# 	"monthly": [
# 		"sas_forcex_fleeto.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "sas_forcex_fleeto.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "sas_forcex_fleeto.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "sas_forcex_fleeto.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "sas_forcex_fleeto.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["sas_forcex_fleeto.utils.before_request"]
# after_request = ["sas_forcex_fleeto.utils.after_request"]

# Job Events
# ----------
# before_job = ["sas_forcex_fleeto.utils.before_job"]
# after_job = ["sas_forcex_fleeto.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"sas_forcex_fleeto.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# ---------------------------------------------------------------------------
# ForceX FLEETO — service & warranty module (sas_forcex_fleeto.forcex_fleeto)
# ---------------------------------------------------------------------------

# Roles first (DocType permissions reference them), custom fields after.
# All idempotent, so safe on every install / migrate.
before_install = "sas_forcex_fleeto.forcex_fleeto.install.before_install"
before_migrate = ["sas_forcex_fleeto.forcex_fleeto.install.before_migrate"]
after_install = "sas_forcex_fleeto.forcex_fleeto.install.after_install"
after_migrate = ["sas_forcex_fleeto.forcex_fleeto.install.after_migrate"]

scheduler_events = {
	# 06:15 IST daily, before the Feedback Desk starts calling
	"cron": {"15 6 * * *": ["sas_forcex_fleeto.forcex_fleeto.tasks.build_feedback_queue"]},
}
