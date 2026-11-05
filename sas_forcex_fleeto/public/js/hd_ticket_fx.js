// HD Ticket (Desk form) — FLEETO service & warranty behaviour.
//
// Loaded via hooks.py doctype_js. The Helpdesk agent app gets the same stage
// actions from the "FLEETO stage actions" HD Form Script. Business rules stay on
// the SERVER (integrations/helpdesk.py); this file only adds convenience:
//   1. Konnect lookup: type a serial / invoice / chassis / mobile, pick the vehicle
//   2. evidence hint while the warranty claim is still Draft
//   3. one button per allowed next stage

const FX_API = "sas_forcex_fleeto.forcex_fleeto.integrations.helpdesk.";
const FX_LANES = ["Service", "Warranty"];
const FX_EVIDENCE_BY_CLAIM = {
	"Customer Claim": "fx_customer_invoice",
	"Instore - Dealer": "fx_distributor_invoice",
	"Instore - Distributor": "fx_tally_invoice",
};

frappe.ui.form.on("HD Ticket", {
	refresh(frm) {
		if (!FX_LANES.includes(frm.doc.ticket_type) || frm.is_new()) return;
		fx_stage_buttons(frm);
		fx_evidence_hint(frm);
		frm.add_custom_button(__("Konnect Lookup"), () => fx_lookup(frm), __("FLEETO"));
	},
	fx_claim_for: fx_evidence_hint,
	fx_customer_invoice: fx_evidence_hint,
	fx_distributor_invoice: fx_evidence_hint,
	fx_tally_invoice: fx_evidence_hint,
	fx_component_photo: fx_evidence_hint,
	fx_odometer_photo: fx_evidence_hint,
});

function fx_stage_buttons(frm) {
	frappe.call(FX_API + "next_stages", { ticket: frm.doc.name }).then(({ message: next }) => {
		(next || []).forEach((stage) => {
			frm.add_custom_button(__(stage), () => {
				const method = stage === "Material Received" ? "receive_material" : "set_stage";
				frappe.confirm(__("Move ticket to {0}?", [__(stage)]), () =>
					frappe.call(FX_API + method, { ticket: frm.doc.name, stage }).then(() => frm.reload_doc())
				);
			}, __("Stage: {0}", [__(frm.doc.fx_stage || "Draft")]));
		});
	});
}

function fx_lookup(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Konnect Lookup"),
		fields: [
			{ fieldname: "search_by", fieldtype: "Select", label: __("Search By"), default: "Serial Number",
				options: "Serial Number\nInvoice Number\nChassis No\nCustomer Mobile" },
			{ fieldname: "query", fieldtype: "Data", label: __("Lookup Query"), reqd: 1 },
		],
		primary_action_label: __("Search"),
		primary_action: ({ search_by, query }) =>
			frappe.call("sas_forcex_fleeto.forcex_fleeto.api.intake.lookup_vehicle", { search_by, query })
				.then(({ message: hits }) => {
					if (!hits || !hits.length) {
						frappe.show_alert({ message: __("No vehicle found in Konnect data"), indicator: "orange" });
						return;
					}
					const hit = hits[0]; // first match; the list view shows all if more
					frm.set_value("fx_vehicle", hit.name);
					if (hit.matched_serial) frm.set_value("fx_component_serial", hit.matched_serial);
					if (hits.length > 1) frappe.show_alert(__("{0} vehicles matched; using {1}", [hits.length, hit.name]));
					d.hide();
				}),
	});
	d.show();
}

function fx_evidence_hint(frm) {
	if (frm.doc.ticket_type !== "Warranty" || (frm.doc.fx_stage || "Draft") !== "Draft") return;
	const missing = [];
	const inv = FX_EVIDENCE_BY_CLAIM[frm.doc.fx_claim_for || "Customer Claim"];
	if (!frm.doc[inv]) missing.push(frappe.meta.get_label(frm.doctype, inv));
	if (!frm.doc.fx_component_photo && !frm.doc.fx_odometer_photo) missing.push(__("Component or Odometer Photo"));
	frm.dashboard.set_headline(
		missing.length
			? `<span class="text-danger">${__("Required before submit")}: ${missing.join(", ")}</span>`
			: `<span class="text-success">${__("Evidence complete")}</span>`
	);
}
