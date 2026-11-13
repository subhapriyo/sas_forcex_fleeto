// FX WhatsApp Settings: "Send Test Message" (adapters/whatsapp.py › send_test)
frappe.ui.form.on("FX WhatsApp Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Send Test Message"), () => fx_whatsapp_test(frm));
		if (frm.doc.last_test_status) {
			const ok = frm.doc.last_test_status.startsWith("OK");
			frm.dashboard.set_headline_alert(
				`${ok ? "✅" : "❌"} ${frappe.utils.escape_html(frm.doc.last_test_status)}`,
				ok ? "green" : "orange"
			);
		}
	},
});

function fx_whatsapp_test(frm) {
	if (!frm.doc.test_mobile) {
		frappe.msgprint(__("Enter a Test Mobile Number first."));
		frm.scroll_to_field("test_mobile");
		return;
	}
	const run = () =>
		frappe
			.call({
				method: "sas_forcex_fleeto.forcex_fleeto.adapters.whatsapp.send_test",
				args: { mobile: frm.doc.test_mobile },
				freeze: true,
				freeze_message: __("Sending test message..."),
			})
			.then(({ message: r }) => {
				frappe.msgprint({
					title: r.ok ? __("Test message sent") : __("Test message not sent"),
					indicator: r.ok ? "green" : "red",
					message: frappe.utils.escape_html(r.detail),
				});
				frm.reload_doc();
			});
	// Test what is on screen, not what was last saved
	frm.is_dirty() ? frm.save().then(run) : run();
}
