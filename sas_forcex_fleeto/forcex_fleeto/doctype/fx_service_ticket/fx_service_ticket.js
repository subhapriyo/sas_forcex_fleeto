// FX Service Ticket — Desk form behaviour (Screens 1 & 2).
//
// Keep business rules on the SERVER (fx_service_ticket.py). This file only:
//   1. runs the Konnect lookup and fills the vehicle,
//   2. shows which evidence is still missing (a hint — the server enforces it),
//   3. renders one button per allowed next status.

const EVIDENCE_BY_CLAIM = {
	"Customer Claim": "customer_invoice",
	"Instore - Dealer": "distributor_invoice",
	"Instore - Distributor": "tally_invoice",
};

frappe.ui.form.on("FX Service Ticket", {
	refresh(frm) {
		render_status_buttons(frm);
		show_evidence_hint(frm);

		if (frm.doc.status === "Open" && frm.doc.ticket_type === "Warranty") {
			frm.add_custom_button(__("Material Received"), () =>
				frm.call("receive_material").then(() => frm.reload_doc())
			);
		}
	},

	// ---- 1. Lookup ------------------------------------------------------
	lookup_query(frm) {
		if (!frm.doc.lookup_query) return;
		frappe
			.call("sas_forcex_fleeto.forcex_fleeto.api.intake.lookup_vehicle", {
				search_by: frm.doc.search_by,
				query: frm.doc.lookup_query,
			})
			.then(({ message: hits }) => {
				if (!hits || !hits.length) {
					frappe.show_alert({ message: __("No vehicle found in Konnect data"), indicator: "orange" });
					return;
				}
				if (hits.length === 1) return apply_hit(frm, hits[0]);
				// More than one match (e.g. mobile with two vehicles): let the user pick.
				const d = new frappe.ui.Dialog({
					title: __("Select vehicle"),
					fields: [{ fieldname: "chassis", fieldtype: "Select", label: __("Vehicle"), reqd: 1,
						options: hits.map((h) => ({ value: h.name, label: `${h.name} · ${h.customer_name} · ${h.model}` })) }],
					primary_action: ({ chassis }) => { apply_hit(frm, hits.find((h) => h.name === chassis)); d.hide(); },
				});
				d.show();
			});
	},

	claim_for: show_evidence_hint,
	customer_invoice: show_evidence_hint,
	distributor_invoice: show_evidence_hint,
	tally_invoice: show_evidence_hint,
	component_photo: show_evidence_hint,
	odometer_photo: show_evidence_hint,
});

function apply_hit(frm, hit) {
	frm.set_value("vehicle", hit.name); // fetch_from fills customer, mobile, invoice, sale date
	if (hit.matched_serial) {
		frm.set_value("component_serial", hit.matched_serial);
		frm.set_value("component_type", hit.matched_component_type);
	}
}

// ---- 2. Evidence hint ------------------------------------------------------
function show_evidence_hint(frm) {
	if (frm.doc.ticket_type !== "Warranty" || frm.doc.status !== "Draft") return frm.dashboard.clear_headline();
	const missing = [];
	const inv = EVIDENCE_BY_CLAIM[frm.doc.claim_for || "Customer Claim"];
	if (!frm.doc[inv]) missing.push(frappe.meta.get_label(frm.doctype, inv));
	if (!frm.doc.component_photo && !frm.doc.odometer_photo) missing.push(__("Component or Odometer Photo"));
	frm.dashboard.set_headline(
		missing.length
			? `<span class="text-danger">${__("Required before submit")}: ${missing.join(", ")}</span>`
			: `<span class="text-success">${__("Evidence complete")}</span>`
	);
}

// ---- 3. Status buttons -----------------------------------------------------
function render_status_buttons(frm) {
	if (frm.is_new()) return;
	const next = (frm.doc.__onload || {}).next_statuses || [];
	next.forEach((status) => {
		frm.add_custom_button(__(status), () =>
			frappe.confirm(__("Move ticket to {0}?", [__(status)]), () =>
				frm.call("set_status", { new_status: status }).then(() => frm.reload_doc())
			), __("Move to")
		);
	});
}
