// Feedback Desk (SOW screens 7-8).
// "Next call" hands the executive the oldest customer in the queue. The server locks the row,
// so two executives never get the same person. The executive asks the questions and records
// ONE outcome; every rule (required answers, retry limit, detractor alert, WhatsApp thank-you)
// runs on the server in FX Feedback Call.submit_outcome, never here.
const FX_DESK_API = "sas_forcex_fleeto.forcex_fleeto.api.feedback_desk";

frappe.pages["fx-feedback-desk"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Feedback Desk"), single_column: true });
	wrapper.fx_desk = new FXFeedbackDesk(page);
};
// Fresh counts each time the page is opened; hand back an unfinished call when leaving it.
frappe.pages["fx-feedback-desk"].on_page_show = (wrapper) => wrapper.fx_desk && wrapper.fx_desk.summary();
frappe.pages["fx-feedback-desk"].on_page_hide = (wrapper) => wrapper.fx_desk && wrapper.fx_desk.release();

class FXFeedbackDesk {
	constructor(page) {
		this.page = page;
		this.call = null; // the call this executive holds right now
		page.set_primary_action(__("Next call"), () => this.next(), "phone-call");
		page.add_menu_item(__("All feedback calls (list)"), () => frappe.set_route("List", "FX Feedback Call"));
		fx_desk_styles();
		const $root = $('<div class="fx-desk"></div>').appendTo(page.main);
		this.$stats = $('<section class="fxd-stats" aria-label="Queue today"></section>').appendTo($root);
		this.$body = $("<div></div>").appendTo($root);
		this.idle(__("Ready for the next customer"), __("Calls come in invoice-date order, oldest first."));
		this.summary();
	}

	// One strip of four numbers rather than four separate cards: they are read together.
	summary() {
		frappe.call(`${FX_DESK_API}.queue_summary`).then(({ message: s }) => {
			const stat = (label, value, tone = "") =>
				`<div class="fxd-stat ${tone}"><span>${label}</span><strong>${value}</strong></div>`;
			this.$stats.html(
				stat(__("Waiting"), s.pending) +
					stat(__("Call back later"), s.on_hold) +
					stat(__("Completed today"), s.completed_today, "is-good") +
					stat(__("Detractors today"), s.detractors_today, s.detractors_today ? "is-bad" : "")
			);
		});
	}

	// Empty state: say what happens next and offer the one action that moves things on.
	idle(title, detail) {
		this.call = null;
		this.$body.html(`
			<section class="fxd-idle">
				<h4>${title}</h4>
				<p>${detail}</p>
				<button class="btn btn-primary btn-sm fxd-next">${__("Next call")}</button>
			</section>`);
		this.$body.find(".fxd-next").on("click", () => this.next());
	}

	next() {
		this.release().then(() =>
			frappe.call({ method: `${FX_DESK_API}.open_next_call`, freeze: true }).then(({ message: name }) => {
				if (!name) {
					this.idle(__("The queue is clear"), __("No customer is due for a call right now. New invoices join the queue every morning at 6:15."));
					this.summary();
					return;
				}
				return frappe.call(`${FX_DESK_API}.get_call`, { name }).then(({ message: c }) => this.show(c));
			})
		);
	}

	// Give an unfinished call back to the queue (no attempt is counted).
	release() {
		if (!this.call) return Promise.resolve();
		const name = this.call.name;
		this.call = null;
		return frappe.call({ method: `${FX_DESK_API}.release_call`, args: { name } }).catch(() => {});
	}

	show(c) {
		this.call = c;
		this.answers = {}; // {question number: answer}, sent as-is to submit_outcome
		const esc = frappe.utils.escape_html;
		const v = c.vehicle || {};
		const fact = (label, value) => `<div><dt>${label}</dt><dd>${esc(value || "-")}</dd></div>`;

		this.$body.html(`
			<div class="fxd-call">
				<aside class="fxd-customer">
					<div class="fxd-attempt">${__("Attempt {0} of {1}", [(c.attempts || 0) + 1, c.max_attempts || "-"])}</div>
					<h3>${esc(c.customer_name || __("Customer"))}</h3>
					${c.mobile ? `<a class="btn btn-primary btn-sm fxd-dial" href="tel:${esc(c.mobile)}">${__("Call")} ${esc(c.mobile)}</a>` : ""}
					${c.whatsapp && c.whatsapp !== c.mobile ? `<div class="fxd-alt">${__("WhatsApp")} ${esc(c.whatsapp)}</div>` : ""}
					<dl>
						${fact(__("Invoice"), c.invoice_no)}
						${fact(__("Invoice date"), frappe.datetime.str_to_user(c.invoice_date))}
						${fact(__("Model"), v.model || v.product_name)}
						${fact(__("Chassis"), v.chassis_no)}
						${fact(__("Questionnaire"), c.questionnaire_name || c.questionnaire)}
					</dl>
				</aside>
				<section class="fxd-questions" aria-label="${__("Questions")}">
					<h4>${__("Ask the customer")}</h4>
					<ol>${c.answers.map((q) => this.question_html(q)).join("") ||
						`<p class="fxd-muted">${__("This questionnaire has no active questions.")}</p>`}</ol>
				</section>
			</div>
			<div class="fxd-actions">
				<button class="btn btn-primary" data-outcome="Connected">${__("Save answers")}</button>
				<button class="btn btn-default" data-outcome="Not Reachable">${__("Not reachable")}</button>
				<button class="btn btn-default" data-outcome="Call Back Later">${__("Call back later")}</button>
				<button class="btn btn-default" data-outcome="Customer Declined">${__("Customer declined")}</button>
				<button class="btn btn-link fxd-release">${__("Release without calling")}</button>
			</div>`);

		this.bind_questions();
		this.$body.find("[data-outcome]").on("click", (e) => this.submit($(e.currentTarget).attr("data-outcome")));
		this.$body.find(".fxd-release").on("click", () =>
			this.release().then(() => {
				this.idle(__("Call released"), __("The customer is back in the queue for the next executive."));
				this.summary();
			})
		);
	}

	// The input matches the answer type set on the questionnaire.
	question_html(q) {
		const esc = frappe.utils.escape_html;
		const required = q.mandatory ? `<span class="fxd-req">${__("Required")}</span>` : "";
		let input;
		if (q.answer_type === "Star rating (1-5)") {
			input = `<div class="fxd-stars" role="radiogroup" aria-label="${esc(q.question)}">${[1, 2, 3, 4, 5]
				.map((n) => `<button type="button" class="fxd-star" role="radio" aria-checked="false" data-q="${q.idx}" data-v="${n}"
					aria-label="${n}">★</button>`)
				.join("")}</div>`;
		} else if (q.answer_type === "Yes / No / Maybe" || q.answer_type === "Yes / No") {
			const options = q.answer_type === "Yes / No" ? ["Yes", "No"] : ["Yes", "No", "Maybe"];
			input = `<div class="fxd-choice" role="radiogroup" aria-label="${esc(q.question)}">${options
				.map((o) => `<button type="button" class="fxd-pick" role="radio" aria-checked="false" data-q="${q.idx}" data-v="${o}">${__(o)}</button>`)
				.join("")}</div>`;
		} else {
			input = `<textarea class="form-control fxd-text" data-q="${q.idx}" rows="3" aria-label="${esc(q.question)}"></textarea>`;
		}
		return `<li class="fxd-q"><p>${esc(q.question)} ${required}</p>${input}</li>`;
	}

	bind_questions() {
		const $b = this.$body;
		const mark = ($group, $chosen) => {
			$group.attr("aria-checked", "false").removeClass("is-on");
			$chosen.attr("aria-checked", "true").addClass("is-on");
		};
		// A star rating fills every star up to the one clicked.
		$b.find(".fxd-star").on("click", (e) => {
			const $s = $(e.currentTarget), q = $s.attr("data-q"), n = +$s.attr("data-v");
			this.answers[q] = n;
			const $all = $b.find(`.fxd-star[data-q="${q}"]`);
			mark($all, $all.filter((_, el) => +$(el).attr("data-v") <= n));
			$all.filter((_, el) => +$(el).attr("data-v") !== n).attr("aria-checked", "false");
		});
		$b.find(".fxd-pick").on("click", (e) => {
			const $p = $(e.currentTarget), q = $p.attr("data-q");
			this.answers[q] = $p.attr("data-v");
			mark($b.find(`.fxd-pick[data-q="${q}"]`), $p);
		});
		$b.find(".fxd-text").on("input", (e) => {
			const $t = $(e.currentTarget);
			this.answers[$t.attr("data-q")] = $t.val();
		});
	}

	submit(outcome) {
		if (!this.call) return;
		const send = (callback_at) =>
			frappe
				.call({
					method: `${FX_DESK_API}.submit_call`,
					args: {
						name: this.call.name,
						outcome,
						// Answers only count when the customer actually spoke to us.
						answers: outcome === "Connected" ? JSON.stringify(this.answers) : null,
						callback_at: callback_at || null,
					},
					freeze: true,
				})
				.then(({ message: r }) => {
					const who = frappe.utils.escape_html(this.call.customer_name || __("Customer"));
					this.call = null;
					if (r.is_detractor) {
						frappe.show_alert({ message: __("Low rating saved. The Warranty Service Head has been alerted."), indicator: "orange" }, 8);
					}
					this.idle(__("Saved: {0} is now {1}", [who, __(r.status)]), __("Take the next customer when you're ready."));
					this.summary();
				});

		if (outcome === "Call Back Later") {
			frappe.prompt(
				{ fieldname: "at", fieldtype: "Datetime", label: __("Call back at"), reqd: 1 },
				(v) => send(v.at),
				__("When should we call back?"),
				__("Save")
			);
		} else {
			send();
		}
	}
}

// Scoped styles on one 8px grid. Surfaces use Desk's theme variables (dark mode keeps working);
// only the ForceX navy and orange are fixed.
function fx_desk_styles() {
	if (document.getElementById("fx-desk-styles")) return;
	$(`<style id="fx-desk-styles">
		.fx-desk { --fx-navy: #0B2A4A; --fx-orange: #F07C1E; padding: 8px 0 0;
			font-variant-numeric: tabular-nums; }
		.fx-desk h3, .fx-desk h4 { margin: 0; font-weight: 600; }
		.fxd-muted { color: var(--text-muted); }

		/* Counters */
		.fxd-stats { display: grid; grid-template-columns: repeat(4, 1fr); margin-bottom: 24px; background: var(--card-bg);
			border: 1px solid var(--border-color); border-radius: 12px; }
		.fxd-stat { display: flex; flex-direction: column; gap: 4px; padding: 16px; border-left: 1px solid var(--border-color); }
		.fxd-stat:first-child { border-left: 0; }
		.fxd-stat span { color: var(--text-muted); font-size: 13px; }
		.fxd-stat strong { font-size: 24px; font-weight: 600; line-height: 1.2; }
		.fxd-stat.is-good strong { color: var(--green-600, #16a34a); }
		.fxd-stat.is-bad strong { color: var(--red-600, #dc2626); }

		/* Empty state */
		.fxd-idle { padding: 48px 24px; text-align: center; background: var(--card-bg); border: 1px dashed var(--border-color);
			border-radius: 12px; }
		.fxd-idle p { margin: 8px auto 16px; max-width: 440px; color: var(--text-muted); }

		/* Call: customer on the left (stays in view while scrolling), questions on the right */
		.fxd-call { display: grid; grid-template-columns: 320px 1fr; gap: 24px; align-items: start; }
		.fxd-customer, .fxd-questions { padding: 24px; background: var(--card-bg); border: 1px solid var(--border-color);
			border-radius: 12px; }
		.fxd-customer { position: sticky; top: 96px; display: flex; flex-direction: column; gap: 8px; }
		.fxd-customer h3 { font-size: 20px; line-height: 1.3; }
		.fxd-attempt { align-self: flex-start; padding: 2px 10px; border-radius: 12px; background: var(--subtle-fg);
			color: var(--text-muted); font-size: 12px; }
		.fxd-dial { align-self: flex-start; background: var(--fx-navy); border-color: var(--fx-navy); }
		.fxd-alt { color: var(--text-muted); font-size: 13px; }
		.fxd-customer dl { display: grid; gap: 12px; margin: 8px 0 0; padding-top: 16px; border-top: 1px solid var(--border-color); }
		.fxd-customer dt { color: var(--text-muted); font-size: 12px; font-weight: 400; }
		.fxd-customer dd { margin: 0; overflow-wrap: anywhere; }

		/* Questions: a real sequence, so they are numbered */
		.fxd-questions h4 { font-size: 16px; margin-bottom: 8px; }
		.fxd-questions ol { margin: 0; padding-left: 20px; }
		.fxd-q { padding: 16px 0; border-top: 1px solid var(--border-color); }
		.fxd-q:first-child { border-top: 0; }
		.fxd-q::marker { color: var(--text-muted); }
		.fxd-q > p { margin: 0 0 8px; }
		.fxd-req { margin-left: 4px; color: var(--text-muted); font-size: 12px; }
		.fxd-stars { display: flex; gap: 4px; }
		.fxd-star { width: 40px; height: 40px; border: 0; border-radius: 8px; background: transparent; font-size: 28px;
			line-height: 1; color: var(--gray-300, #d1d5db); }
		.fxd-star.is-on { color: var(--fx-orange); }
		.fxd-star:hover { background: var(--subtle-fg); }
		.fxd-choice { display: inline-flex; border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; }
		.fxd-pick { min-width: 72px; padding: 6px 16px; border: 0; border-left: 1px solid var(--border-color);
			background: var(--card-bg); color: var(--text-color); }
		.fxd-pick:first-child { border-left: 0; }
		.fxd-pick.is-on { background: var(--fx-navy); color: #fff; }
		.fxd-star:focus-visible, .fxd-pick:focus-visible { outline: 2px solid var(--fx-orange); outline-offset: -2px; }

		/* Outcome bar stays at the bottom of the screen while the executive scrolls */
		.fxd-actions { position: sticky; bottom: 0; z-index: 2; display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
			margin-top: 24px; padding: 16px 0; background: var(--bg-color); border-top: 1px solid var(--border-color); }
		.fxd-actions .btn-primary { background: var(--fx-navy); border-color: var(--fx-navy); }
		.fxd-release { margin-left: auto; }

		@media (max-width: 900px) {
			.fxd-stats { grid-template-columns: repeat(2, 1fr); }
			.fxd-stat:nth-child(3) { border-left: 0; }
			.fxd-stat:nth-child(n + 3) { border-top: 1px solid var(--border-color); }
			.fxd-call { grid-template-columns: 1fr; }
			.fxd-customer { position: static; }
		}
	</style>`).appendTo(document.head);
}
