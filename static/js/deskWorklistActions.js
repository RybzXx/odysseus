/* static/js/deskWorklistActions.js
 *
 * The worklist controls the itinerary desk was missing.
 *
 * Every action below already existed in the Operations modal and nowhere else,
 * so a reviewer working on the desk had to change surface to move a request,
 * write a note, copy a reply or send a change to the live worklist. These call
 * the same routes the modal calls, so the two surfaces cannot drift in
 * behaviour — only in layout.
 *
 * Colour follows the desk's rule: these are a person's own presses, so they
 * carry the `human` actor.
 *
 * This file depends on nothing the desk defines. It carries its own escaping
 * and its own fetch, in the shape `briefCard.js` uses.
 */
(function (root) {
  "use strict";

  const STATUSES = ["New", "In Progress", "Replied", "On Hold", "Confirmed",
                    "Rejected"];
  const MODERATIONS = ["flagged", "spam"];

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/[&<>"]/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  /**
   * Post: the decoded body of a 2xx answer.
   * Blame: a non-2xx raises with the status and the body, because a caller
   *        that swallowed it would report a staged change nobody staged.
   */
  async function call(path, options) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin", ...options,
    });
    if (!res.ok) {
      throw new Error(`${res.status} ${(await res.text()).slice(0, 240)}`);
    }
    return res.json();
  }

  /* ── move this request ───────────────────────────────────────────────── */

  /**
   * The controls that change a request's own state.
   *
   * Pre:  `row` is the worklist row the desk holds, carrying `key` and
   *       `updated_at`. A row with no key renders a reason rather than a
   *       control, because staging without one cannot address anything.
   * Post: HTML. Nothing is staged until a press.
   */
  function moveHtml(row) {
    if (!row || !row.key) {
      return `<div class="note">This draft names no worklist request, so there
        is no row to move.</div>`;
    }
    const status = row.status || "New";
    const pills = STATUSES.map((s) =>
      `<button type="button" class="chip wl-status${s === status ? " active" : ""}"
         data-status="${esc(s)}">${esc(s)}</button>`).join("");
    const mods = MODERATIONS.map((m) =>
      `<button type="button" class="chip wl-mod${row.moderation === m ? " active" : ""}"
         data-mod="${esc(m)}">${esc(m)}</button>`).join("");
    return `
      <div class="wl-grid">
        <div class="k">Status</div><div class="row">${pills}</div>
        <div class="k">Moderation</div><div class="row">${mods}
          <button type="button" class="chip wl-mod" data-mod="">none</button></div>
        <div class="k">Operator</div>
        <div><input type="text" id="wl-operator" value="${esc(row.operator || "")}"
               placeholder="nobody assigned"></div>
        <div class="k">Next action</div>
        <div><input type="text" id="wl-date" value="${esc(row.next_action_date || "")}"
               placeholder="YYYY-MM-DD"></div>
      </div>
      <div class="row" style="margin-top:10px">
        <button id="wl-stage" class="primary">Queue this change</button>
        <button id="wl-note">Add a note</button>
        <button id="wl-claude">Queue for Claude</button>
        <span class="note" id="wl-msg"></span>
      </div>
      <div class="note" style="margin-top:6px">Queued changes stay on this
        machine until you send them.</div>`;
  }

  /**
   * Wire the move controls.
   *
   * Pre:  `holder` holds the markup `moveHtml` produced, and `row` is the same
   *       row it was built from.
   * Post: a press stages, notes or queues, and `afterChange` runs so the
   *       caller can reload. Nothing reaches Supabase here — `sendHtml` owns
   *       that press.
   */
  function wireMove(holder, row, afterChange) {
    if (!holder || !row || !row.key) return;
    const chosen = { status: row.status || "New", moderation: row.moderation || "" };
    const say = (text, bad) => {
      const msg = holder.querySelector("#wl-msg");
      if (msg) { msg.innerHTML = bad ? `<span class="err">${esc(text)}</span>`
                                     : esc(text); }
    };

    holder.querySelectorAll(".wl-status").forEach((b) =>
      b.addEventListener("click", () => {
        chosen.status = b.dataset.status;
        holder.querySelectorAll(".wl-status").forEach((o) =>
          o.classList.toggle("active", o === b));
      }));
    holder.querySelectorAll(".wl-mod").forEach((b) =>
      b.addEventListener("click", () => {
        chosen.moderation = b.dataset.mod;
        holder.querySelectorAll(".wl-mod").forEach((o) =>
          o.classList.toggle("active", o === b));
      }));

    holder.querySelector("#wl-stage")?.addEventListener("click", async () => {
      say("queueing…");
      try {
        await call("/api/operations/stage", {
          method: "POST",
          body: JSON.stringify({
            key: row.key,
            status: chosen.status,
            operator: holder.querySelector("#wl-operator").value || "",
            next_action_date: holder.querySelector("#wl-date").value || "",
            moderation: chosen.moderation,
            expected_updated_at: row.updated_at || null,
            rationale: "queued from the itinerary desk",
          }),
        });
        say("queued. Send it from Waiting to send.");
        afterChange && afterChange();
      } catch (e) { say(e.message, true); }
    });

    holder.querySelector("#wl-note")?.addEventListener("click", async () => {
      const text = window.prompt("What should the note say?");
      if (!text || !text.trim()) return;
      say("saving…");
      try {
        await call("/api/operations/notes", {
          method: "POST",
          body: JSON.stringify({ key: row.key, text: text.trim() }),
        });
        say("note saved");
        afterChange && afterChange();
      } catch (e) { say(e.message, true); }
    });

    holder.querySelector("#wl-claude")?.addEventListener("click", async () => {
      say("queueing…");
      try {
        await call("/api/operations/agent-queue", {
          method: "POST", body: JSON.stringify({ key: row.key }),
        });
        say("queued for Claude");
        afterChange && afterChange();
      } catch (e) { say(e.message, true); }
    });
  }

  /* ── waiting to send ─────────────────────────────────────────────────── */

  /**
   * Post: every change queued on this machine, and the one press that writes
   *       them to the worklist the team reads.
   *
   * A conflict is shown and never sent. `_push_staged_changes` keeps it and
   * marks it rather than writing over a row that moved.
   */
  function sendHtml(staged) {
    const rows = staged || [];
    if (!rows.length) {
      return `<div class="note">Nothing is queued.</div>`;
    }
    const list = rows.map((s) => {
      const patch = Object.entries(s.patch || {})
        .map(([k, v]) => `${esc(k)}: ${esc(v === null ? "none" : v)}`).join(" · ");
      return `<div class="turn">
          <div class="row"><strong>${esc(s.key)}</strong>
            ${s.conflict ? '<span class="badge fault">conflict</span>' : ""}
            <span class="grow"></span>
            <button class="wl-discard" data-id="${esc(s.id)}">Discard</button></div>
          <div class="note">${patch || "no change"}</div>
          ${s.conflict ? `<div class="warn">The row moved since this was
            queued, so it will not be sent. Discard it and queue it
            again.</div>` : ""}
        </div>`;
    }).join("");
    const sendable = rows.filter((s) => !s.conflict).length;
    return `${list}
      <div class="row" style="margin-top:10px">
        <button id="wl-send" class="primary" ${sendable ? "" : "disabled"}
          title="Writes to the worklist your whole team reads. This cannot be undone from here.">
          Send ${sendable} change${sendable === 1 ? "" : "s"} to the live worklist</button>
        <span class="note" id="wl-send-msg"></span>
      </div>`;
  }

  function wireSend(holder, afterChange) {
    if (!holder) return;
    const say = (text, bad) => {
      const msg = holder.querySelector("#wl-send-msg");
      if (msg) { msg.innerHTML = bad ? `<span class="err">${esc(text)}</span>`
                                     : esc(text); }
    };
    holder.querySelectorAll(".wl-discard").forEach((b) =>
      b.addEventListener("click", async () => {
        try {
          await call(`/api/operations/staged/${encodeURIComponent(b.dataset.id)}`,
                     { method: "DELETE" });
          afterChange && afterChange();
        } catch (e) { say(e.message, true); }
      }));
    holder.querySelector("#wl-send")?.addEventListener("click", async () => {
      say("sending…");
      try {
        const out = await call("/api/operations/push", { method: "POST" });
        const pushed = (out.pushed || []).length;
        const bad = (out.conflicted || []).length + (out.failed || []).length;
        say(`${pushed} sent${bad ? `, ${bad} kept back` : ""}`);
        afterChange && afterChange();
      } catch (e) { say(e.message, true); }
    });
  }

  /* ── the reply, once a document exists ───────────────────────────────── */

  /**
   * Post: the two drafts on their own buttons, and the press that records the
   *       status once you have sent one.
   *
   * Pre:  `built` is the answer from a generate call, carrying `draft_email`
   *       and `draft_whatsapp`.
   *
   * Nothing here sends a message. The drafts reach the clipboard and you send
   * them from your own client, which is what the status change then records.
   */
  function replyHtml(built) {
    if (!built || (!built.draft_email && !built.draft_whatsapp)) return "";
    const subject = (built.draft_email || {}).subject || "";
    return `<div class="card">
        <div class="row">
          <button id="wl-copy-email" ${built.draft_email ? "" : "disabled"}>
            Copy the email draft</button>
          <button id="wl-copy-wa" ${built.draft_whatsapp ? "" : "disabled"}>
            Copy the WhatsApp draft</button>
          <button id="wl-replied" class="primary">Mark as replied, once you have sent it</button>
          <span class="note" id="wl-reply-msg"></span>
        </div>
        ${subject ? `<div class="note" style="margin-top:6px">Subject:
          ${esc(subject)}</div>` : ""}
      </div>`;
  }

  function wireReply(holder, built, row, afterChange) {
    if (!holder || !built) return;
    const say = (text, bad) => {
      const msg = holder.querySelector("#wl-reply-msg");
      if (msg) { msg.innerHTML = bad ? `<span class="err">${esc(text)}</span>`
                                     : esc(text); }
    };
    const copy = (text, what) => {
      navigator.clipboard.writeText(text)
        .then(() => say(`${what} copied`))
        .catch(() => say("the clipboard refused", true));
    };
    holder.querySelector("#wl-copy-email")?.addEventListener("click", () => {
      const mail = built.draft_email || {};
      copy(`${mail.subject || ""}\n\n${mail.body || ""}`.trim(), "the email");
    });
    holder.querySelector("#wl-copy-wa")?.addEventListener("click", () =>
      copy(built.draft_whatsapp || "", "the WhatsApp draft"));
    holder.querySelector("#wl-replied")?.addEventListener("click", async () => {
      if (!row || !row.key) { say("this draft names no worklist request", true); return; }
      say("recording…");
      try {
        await call("/api/operations/itinerary/stage-reply", {
          method: "POST",
          body: JSON.stringify({
            key: row.key, doc_url: built.doc_url || "",
            email_draft: built.draft_email || null, status: "Replied",
            rationale: "marked replied from the itinerary desk",
          }),
        });
        say("queued. Send it from Waiting to send.");
        afterChange && afterChange();
      } catch (e) { say(e.message, true); }
    });
  }

  root.DeskWorklist = {
    moveHtml, wireMove, sendHtml, wireSend, replyHtml, wireReply,
    staged: () => call("/api/operations/staged"),
    escape: esc,
  };
})(window);
