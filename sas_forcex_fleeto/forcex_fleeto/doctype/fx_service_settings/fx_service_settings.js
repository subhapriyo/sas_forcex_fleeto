// FX Service Settings: Konnect buttons (api/konnect.py)
const FX_KONNECT = "sas_forcex_fleeto.forcex_fleeto.api.konnect";

frappe.ui.form.on("FX Service Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Konnect Connection"), () => fx_konnect_test(frm), __("Konnect"));
		frm.add_custom_button(__("Upload Konnect Report"), () => fx_konnect_upload(), __("Konnect"));
	},
});

function fx_konnect_test(frm) {
	const run = () =>
		frappe.call({ method: `${FX_KONNECT}.test_connection`, freeze: true }).then(({ message: r }) => {
			const rows = r.checks
				.map(
					(c) =>
						`<tr><td>${c.ok ? "✅" : "❌"}</td><td>${frappe.utils.escape_html(c.check)}</td>` +
						`<td class="text-muted">${frappe.utils.escape_html(c.detail || "")}</td></tr>`
				)
				.join("");
			frappe.msgprint({
				title: r.ok ? __("Konnect connection OK") : __("Konnect connection: check the items below"),
				indicator: r.ok ? "green" : "orange",
				message: `<table class="table table-sm">${rows}</table>`,
			});
		});
	// Test what is on screen, not what was last saved
	frm.is_dirty() ? frm.save().then(run) : run();
}

function fx_konnect_upload() {
	new frappe.ui.FileUploader({
		restrictions: { allowed_file_types: [".xlsx"] },
		on_success(file) {
			frappe
				.call({ method: `${FX_KONNECT}.upload_invoice_report`, args: { file_url: file.file_url } })
				.then(({ message: log }) => {
					frappe.show_alert({ message: __("Import queued: {0}", [log]), indicator: "blue" });
					frappe.set_route("Form", "FX Konnect Import Log", log);
				});
		},
	});
}

window.fx_konnect_upload = fx_konnect_upload;
