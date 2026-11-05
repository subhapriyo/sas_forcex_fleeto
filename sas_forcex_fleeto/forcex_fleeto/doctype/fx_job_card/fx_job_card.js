// FX Job Card — capture GPS on arrival from the technician's phone.
// The browser asks for location permission once; Desk must be served over HTTPS.

frappe.ui.form.on("FX Job Card", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.doc.arrival_time) {
			frm.add_custom_button(__("Mark Arrival (GPS)"), () => mark_arrival(frm)).addClass("btn-primary");
		}
		if (frm.doc.docstatus === 0 && frm.doc.arrival_time && !frm.doc.departure_time) {
			frm.add_custom_button(__("Mark Departure"), () => frm.set_value("departure_time", frappe.datetime.now_datetime()));
		}
	},
});

function mark_arrival(frm) {
	if (!navigator.geolocation) {
		frappe.msgprint(__("This device cannot share its location."));
		return;
	}
	navigator.geolocation.getCurrentPosition(
		(pos) => {
			frm.set_value({
				arrival_time: frappe.datetime.now_datetime(),
				arrival_lat: pos.coords.latitude,
				arrival_lng: pos.coords.longitude,
			});
		},
		(err) => frappe.msgprint(__("Could not read GPS: {0}", [err.message])),
		{ enableHighAccuracy: true, timeout: 15000 }
	);
}
