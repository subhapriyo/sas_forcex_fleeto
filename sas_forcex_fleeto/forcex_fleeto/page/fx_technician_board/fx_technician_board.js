// Screen 3: Technician Board. One day, one row per technician, one column per roster slot.
// Reads api/technician_board.get_board; books through book_slot, so the server's
// overlap check + row lock still decide whether a slot can be taken.
const FX_BOARD_API = "sas_forcex_fleeto.forcex_fleeto.api.technician_board";

frappe.pages["fx-technician-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Technician Board"),
		single_column: true,
	});
	wrapper.fx_board = new FXTechnicianBoard(page);
};

frappe.pages["fx-technician-board"].on_page_show = function (wrapper) {
	wrapper.fx_board && wrapper.fx_board.refresh();
};

class FXTechnicianBoard {
	constructor(page) {
		this.page = page;
		this.date = (frappe.route_options && frappe.route_options.date) || frappe.datetime.get_today();
		frappe.route_options = null;

		this.date_field = page.add_field({
			fieldname: "date",
			fieldtype: "Date",
			label: __("Date"),
			default: this.date,
			change: () => {
				const d = this.date_field.get_value();
				if (d && d !== this.date) {
					this.date = d;
					this.refresh();
				}
			},
		});
		page.add_inner_button(__("◀ Previous day"), () => this.go(frappe.datetime.add_days(this.date, -1)));
		page.add_inner_button(__("Today"), () => this.go(frappe.datetime.get_today()));
		page.add_inner_button(__("Next day ▶"), () => this.go(frappe.datetime.add_days(this.date, 1)));
		page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		page.add_menu_item(__("All bookings (list)"), () => frappe.set_route("List", "FX Technician Booking"));

		fx_board_styles();
		this.$body = $('<div class="fx-board"></div>').appendTo(page.main);

		// Someone else booked or cancelled: redraw if this page is open
		frappe.realtime.on("list_update", (d) => {
			if (d && d.doctype === "FX Technician Booking" && frappe.get_route_str() === "fx-technician-board") {
				this.refresh();
			}
		});
	}

	go(date) {
		this.date = date;
		this.date_field.set_value(date);
		this.refresh();
	}

	refresh() {
		if (this.loading) return;
		this.loading = true;
		Promise.all([
			frappe.call(`${FX_BOARD_API}.get_board`, { date: this.date }),
			frappe.call(`${FX_BOARD_API}.bookable_tickets`),
		])
			.then(([board, tickets]) => this.render(board.message, tickets.message || []))
			.finally(() => (this.loading = false));
	}

	render(data, waiting) {
		this.data = data;
		const esc = frappe.utils.escape_html;
		const today = frappe.datetime.get_today();
		const is_past = data.date < today;

		if (!data.rows.length) {
			this.$body.html(`
				<div class="fxb-empty">
					<h4>${__("No technicians to show")}</h4>
					<p>${__("The board lists active Employees whose Designation is in FX Service Settings › Technician Designations.")}</p>
					<a class="btn btn-default btn-sm" href="/desk/fx-service-settings">${__("Open FX Service Settings")}</a>
				</div>`);
			return;
		}

		// The server repeats a booking in every slot it touches; the timeline needs each job once.
		for (const row of data.rows) {
			const jobs = new Map();
			row.cells.forEach((cell) => cell.bookings.forEach((b) => jobs.set(b.name, b)));
			row.jobs = [...jobs.values()];
		}
		const scale = fx_time_scale(data);

		this.$body.html(`
			${this.waiting_html(waiting)}
			<section class="fxb-board" aria-label="${__("Technician timeline for {0}", [frappe.datetime.str_to_user(data.date)])}">
				<div class="fxb-row fxb-head">
					<div class="fxb-tech">${is_past ? __("Past day · view only") : __("Technician")}</div>
					<div class="fxb-track">${scale.ticks.map((t) => `<span class="fxb-tick ${t.edge}" style="left:${t.left}">${t.label}</span>`).join("")}</div>
				</div>
				${data.rows.map((row, r) => this.row_html(row, r, scale, is_past, data.date === today)).join("")}
			</section>
			<footer class="fxb-legend">
				<span class="fxb-job is-assigned">${__("Assigned")}</span>
				<span class="fxb-job is-in_progress">${__("In Progress")}</span>
				<span class="fxb-job is-done">${__("Done")}</span>
				<span class="fxb-job is-blocked">${__("Blocked")}</span>
				<span class="fxb-job is-cancelled">${__("Cancelled")}</span>
				<span class="fxb-note">${__("Shaded bands are the roster slots. A slot is free unless an Assigned, In Progress or Blocked booking overlaps it.")}</span>
			</footer>`);

		this.$body.find("[data-booking]").on("click", (e) =>
			frappe.set_route("Form", "FX Technician Booking", $(e.currentTarget).attr("data-booking"))
		);
		this.$body.find("[data-book]").on("click", (e) => {
			const [r, c] = $(e.currentTarget).attr("data-book").split(":").map(Number);
			this.book(data.rows[r], data.slots[c]);
		});
	}

	// Tickets nobody has scheduled yet, shown first so the coordinator knows what to place.
	waiting_html(waiting) {
		const esc = frappe.utils.escape_html;
		const chips = waiting
			.map(
				(t) => `<a class="fxb-ticket" href="/helpdesk/tickets/${encodeURIComponent(t.name)}" target="_blank"
					title="${esc(t.fx_stage)}"><strong>#${esc(t.name)}</strong> ${esc(t.subject || "")}</a>`
			)
			.join("");
		return `
			<section class="fxb-waiting">
				<h5>${__("Waiting for a technician")} <span class="fxb-count">${waiting.length}</span></h5>
				<div class="fxb-tickets">${chips || `<span class="fxb-note">${__("Every service ticket has a technician.")}</span>`}</div>
			</section>`;
	}

	row_html(row, r, scale, is_past, is_today) {
		const esc = frappe.utils.escape_html;
		const lanes = fx_lanes(row.jobs);
		const can_add = this.data.can_book && !is_past && row.cells.some((c) => c.free);
		// Height grows with stacked jobs; the extra strip at the bottom holds the "+ Book" buttons.
		const height = 12 + Math.max(lanes.count, 1) * 40 + (can_add ? 32 : 0);

		const bands = row.cells
			.map((cell, c) => {
				const s = this.data.slots[c];
				const add =
					cell.free && can_add
						? `<button class="fxb-add" data-book="${r}:${c}"
							aria-label="${esc(__("Book {0}, {1}", [row.employee_name, s.label]))}">+ ${__("Book")}</button>`
						: "";
				return `<div class="fxb-slot ${cell.free ? "is-free" : ""}" style="${scale.span(s.start, s.end)}">${add}</div>`;
			})
			.join("");

		const jobs = row.jobs
			.map(
				(b) => `<a class="fxb-job is-${frappe.scrub(b.status)}" data-booking="${esc(b.name)}"
					style="${scale.span(b.from_time, b.to_time)};top:${8 + lanes.of[b.name] * 40}px"
					title="${esc([b.subject, `${b.from_time}–${b.to_time}`, __(b.status)].filter(Boolean).join("\n"))}">
					<strong>${b.ticket ? "#" + esc(b.ticket) : esc(__(b.status))}</strong>
					<span>${esc(b.from_time)}–${esc(b.to_time)}</span>
				</a>`
			)
			.join("");

		// Orange line for "now" on today's board, so late jobs stand out at a glance.
		const now = is_today ? scale.now() : null;
		const now_line = now ? `<div class="fxb-now" style="left:${now}" aria-hidden="true"></div>` : "";

		return `
			<div class="fxb-row">
				<div class="fxb-tech">
					<a href="/desk/employee/${encodeURIComponent(row.technician)}">${esc(row.employee_name)}</a>
					<small>${esc(row.designation || "")}</small>
				</div>
				<div class="fxb-track" style="height:${height}px">${bands}${jobs}${now_line}</div>
			</div>`;
	}

	book(row, slot) {
		const d = new frappe.ui.Dialog({
			title: __("Book {0}", [row.employee_name]),
			fields: [
				{
					fieldname: "kind",
					fieldtype: "Select",
					label: __("Booking"),
					options: [
						{ value: "Assigned", label: __("Service visit") },
						{ value: "Blocked", label: __("Blocked (leave / transit / training)") },
					],
					default: "Assigned",
				},
				{
					fieldname: "ticket",
					fieldtype: "Link",
					options: "HD Ticket",
					label: __("Service Ticket"),
					depends_on: "eval:doc.kind=='Assigned'",
					mandatory_depends_on: "eval:doc.kind=='Assigned'",
					description: __("Service tickets at Tele-Calling Triage or Visit Done - Unresolved"),
					get_query: () => ({
						filters: {
							ticket_type: "Service",
							fx_stage: ["in", ["Tele-Calling Triage", "Visit Done - Unresolved"]],
						},
					}),
				},
				{ fieldtype: "Section Break" },
				{ fieldname: "from_time", fieldtype: "Time", label: __("From"), default: slot.start, reqd: 1 },
				{ fieldtype: "Column Break" },
				{ fieldname: "to_time", fieldtype: "Time", label: __("To"), default: slot.end, reqd: 1 },
				{ fieldtype: "Section Break" },
				{
					fieldname: "notify",
					fieldtype: "Check",
					label: __("Send WhatsApp alert to the technician"),
					default: 1,
					depends_on: "eval:doc.kind=='Assigned'",
				},
			],
			primary_action_label: __("Book"),
			primary_action: (v) => {
				frappe
					.call({
						method: `${FX_BOARD_API}.book_slot`,
						args: {
							technician: row.technician,
							date: this.data.date,
							from_time: v.from_time,
							to_time: v.to_time,
							ticket: v.ticket,
							status: v.kind,
							notify: v.notify ? 1 : 0,
						},
						freeze: true,
					})
					.then(() => {
						d.hide();
						frappe.show_alert({ message: __("Booked"), indicator: "green" });
						this.refresh();
					});
			},
		});
		d.show();
	}
}

// Maps clock times to % positions across the day. The day runs from the first roster slot (or
// earlier job) to the last, rounded out to whole hours so the hour ticks line up.
function fx_time_scale(data) {
	const mins = (t) => {
		const [h, m] = String(t).split(":").map(Number);
		return h * 60 + (m || 0);
	};
	const times = data.slots.flatMap((s) => [mins(s.start), mins(s.end)]);
	data.rows.forEach((row) => row.jobs.forEach((b) => times.push(mins(b.from_time), mins(b.to_time))));
	const lo = Math.floor(Math.min(...times) / 60) * 60;
	const hi = Math.ceil(Math.max(...times) / 60) * 60;
	const pct = (m) => `${(((m - lo) / (hi - lo)) * 100).toFixed(3)}%`;

	const ticks = [];
	for (let m = lo; m <= hi; m += 60) {
		const h = m / 60;
		// First and last labels hug the edges so they never spill outside the track.
		const edge = m === lo ? "is-first" : m === hi ? "is-last" : "";
		ticks.push({ left: pct(m), edge, label: `${((h + 11) % 12) + 1} ${h < 12 ? "am" : "pm"}` });
	}
	return {
		ticks,
		span: (a, b) => `left:${pct(mins(a))};width:${pct(lo + mins(b) - mins(a))}`,
		// Uses the ForceX user's time zone (System Settings), not the browser clock's.
		now() {
			const m = mins(frappe.datetime.now_time());
			return m > lo && m < hi ? pct(m) : null;
		},
	};
}

// Stacks jobs that overlap (e.g. a cancelled visit and its replacement) on separate lines
// instead of drawing them on top of each other. Greedy: first line that is free by then.
function fx_lanes(jobs) {
	const ends = [];
	const of = {};
	const start = (b) => b.from_time;
	[...jobs].sort((a, b) => start(a).localeCompare(start(b))).forEach((b) => {
		let lane = ends.findIndex((end) => end <= b.from_time);
		if (lane === -1) lane = ends.push(b.to_time) - 1;
		else ends[lane] = b.to_time;
		of[b.name] = lane;
	});
	return { of, count: ends.length };
}

// Scoped styles. Surfaces and lines use Desk's theme variables so dark mode keeps working;
// only the ForceX navy and orange are fixed. Spacing follows one 8px grid.
function fx_board_styles() {
	if (document.getElementById("fx-board-styles")) return;
	$(`<style id="fx-board-styles">
		.fx-board { --fx-navy: #0B2A4A; --fx-orange: #F07C1E; --fx-gap: 16px; padding: 8px 0 32px;
			font-variant-numeric: tabular-nums; }
		.fx-board h5 { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; font-size: 14px; font-weight: 600; }

		/* Waiting tickets */
		.fxb-waiting { padding: var(--fx-gap); margin-bottom: 24px; background: var(--card-bg);
			border: 1px solid var(--border-color); border-radius: 12px; }
		.fxb-count { min-width: 22px; padding: 0 7px; border-radius: 11px; background: var(--fx-orange); color: #fff;
			font-size: 12px; line-height: 20px; text-align: center; }
		.fxb-tickets { display: flex; flex-wrap: wrap; gap: 8px; }
		.fxb-ticket { max-width: 340px; padding: 6px 12px; border-radius: 8px; background: var(--subtle-fg);
			border-left: 3px solid var(--fx-orange); color: var(--text-color); font-size: 13px;
			white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-decoration: none !important; }
		.fxb-ticket:hover { background: var(--bg-gray); }

		/* Timeline */
		.fxb-board { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; overflow-x: auto; }
		.fxb-row { display: grid; grid-template-columns: 200px minmax(720px, 1fr); border-top: 1px solid var(--border-color); }
		.fxb-row:first-child { border-top: 0; }
		.fxb-tech { display: flex; flex-direction: column; justify-content: center; gap: 2px; padding: 12px var(--fx-gap);
			border-right: 1px solid var(--border-color); }
		.fxb-tech a { font-weight: 600; color: var(--text-color); }
		.fxb-tech small { color: var(--text-muted); font-size: 12px; }
		.fxb-head { position: sticky; top: 0; z-index: 3; background: var(--card-bg); }
		.fxb-head .fxb-tech { color: var(--text-muted); font-size: 12px; }
		.fxb-head .fxb-track { height: 36px; }
		.fxb-track { position: relative; margin: 0 var(--fx-gap); }
		.fxb-tick { position: absolute; top: 10px; transform: translateX(-50%); font-size: 12px; color: var(--text-muted);
			white-space: nowrap; }
		.fxb-tick.is-first { transform: none; }
		.fxb-tick.is-last { transform: translateX(-100%); }
		.fxb-slot { position: absolute; top: 4px; bottom: 4px; border-radius: 8px; background: var(--subtle-fg); }
		.fxb-slot.is-free { background: var(--bg-blue); opacity: .55; }
		.fxb-slot.is-free:hover { opacity: 1; }
		.fxb-add { position: absolute; left: 8px; bottom: 6px; padding: 2px 10px; border: 1px dashed var(--fx-navy);
			border-radius: 6px; background: var(--card-bg); color: var(--fx-navy); font-size: 12px; font-weight: 500; }
		.fxb-add:hover, .fxb-add:focus-visible { background: var(--fx-navy); color: #fff; outline: none; }
		.fxb-now { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--fx-orange); z-index: 2; }

		/* Jobs: colour = commitment level */
		.fxb-job { position: absolute; z-index: 1; height: 32px; display: flex; align-items: center; gap: 8px; padding: 0 10px;
			min-width: 64px; border-radius: 8px; font-size: 12px; white-space: nowrap; overflow: hidden;
			text-decoration: none !important; cursor: pointer; }
		.fxb-job strong { font-weight: 600; }
		.fxb-job.is-assigned { background: var(--fx-navy); color: #fff; }
		.fxb-job.is-in_progress { background: var(--fx-orange); color: #fff; }
		.fxb-job.is-done { background: var(--bg-green); color: var(--text-on-green); }
		.fxb-job.is-blocked { color: var(--text-muted);
			background: repeating-linear-gradient(135deg, var(--border-color) 0 2px, var(--subtle-fg) 2px 8px);
			border: 1px solid var(--border-color); }
		.fxb-job.is-cancelled { background: transparent; color: var(--text-muted); border: 1px dashed var(--border-color);
			text-decoration: line-through !important; }
		.fxb-job:focus-visible { outline: 2px solid var(--fx-orange); outline-offset: 2px; }

		/* Legend + empty state */
		.fxb-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: var(--fx-gap); }
		.fxb-legend .fxb-job { position: static; height: 24px; min-width: 0; cursor: default; }
		.fxb-note { color: var(--text-muted); font-size: 12px; }
		.fxb-legend .fxb-note { margin-left: 8px; }
		.fxb-empty { max-width: 480px; margin: 48px auto; text-align: center; }
		.fxb-empty p { color: var(--text-muted); margin: 8px 0 16px; }
		@media (max-width: 768px) { .fxb-row { grid-template-columns: 140px minmax(640px, 1fr); } }
	</style>`).appendTo(document.head);
}
