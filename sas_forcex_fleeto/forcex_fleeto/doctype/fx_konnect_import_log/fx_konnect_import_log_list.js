// FX Konnect Import Log list: bulk upload of the Konnect Excel export (api/konnect.py)
frappe.listview_settings["FX Konnect Import Log"] = {
	get_indicator(doc) {
		return {
			Queued: [__("Queued"), "blue", "status,=,Queued"],
			Running: [__("Running"), "orange", "status,=,Running"],
			Done: [__("Done"), "green", "status,=,Done"],
			Failed: [__("Failed"), "red", "status,=,Failed"],
		}[doc.status];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Upload Konnect Report"), () => {
			new frappe.ui.FileUploader({
				restrictions: { allowed_file_types: [".xlsx"] },
				on_success(file) {
					frappe
						.call({
							method: "sas_forcex_fleeto.forcex_fleeto.api.konnect.upload_invoice_report",
							args: { file_url: file.file_url },
						})
						.then(({ message: log }) => {
							frappe.show_alert({ message: __("Import queued: {0}", [log]), indicator: "blue" });
							listview.refresh();
						});
				},
			});
		});
	},
};
