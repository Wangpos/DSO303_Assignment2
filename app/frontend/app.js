/* ExamHub single-page app – vanilla JS, no build step.
 * Auth: Cognito hosted UI, authorization code + PKCE. Tokens live in sessionStorage.
 * All DOM is built with el() (textContent), never innerHTML with user data. */
(() => {
  "use strict";
  const C = window.APP_CONFIG;
  const app = document.getElementById("app");

  // ------------------------------------------------------------------ DOM helpers
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (k === "class") node.className = v;
      else if (k === "value") node.value = v;
      else if (k === "checked") node.checked = !!v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  const render = (...nodes) => app.replaceChildren(...nodes);
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
  const toLocalInput = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  const fromLocalInput = (v) => (v ? new Date(v).toISOString() : null);
  const mb = (bytes) => (bytes ? `${(bytes / 1048576).toFixed(1)} MB` : "");

  let toastTimer;
  function toast(msg, isError = false) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.className = "toast" + (isError ? " error" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), isError ? 7000 : 3500);
  }
  function pill(text, kind = "") {
    return el("span", { class: `pill ${kind}` }, text);
  }

  // ------------------------------------------------------------------ auth (PKCE)
  const b64url = (buf) =>
    btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const randomString = (n = 64) => b64url(crypto.getRandomValues(new Uint8Array(n)));

  const auth = {
    get idToken() { return sessionStorage.getItem("id_token"); },
    claims() {
      const t = this.idToken;
      if (!t) return null;
      try {
        return JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      } catch { return null; }
    },
    role() {
      const g = (this.claims() || {})["cognito:groups"] || [];
      if (g.includes("admins")) return "admin";
      if (g.includes("tutors")) return "tutor";
      if (g.includes("students")) return "student";
      return null;
    },
    async login() {
      const verifier = randomString();
      const state = randomString(16);
      sessionStorage.setItem("pkce_verifier", verifier);
      sessionStorage.setItem("pkce_state", state);
      sessionStorage.setItem("return_to", location.hash || "#/");
      const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
      const q = new URLSearchParams({
        response_type: "code", client_id: C.clientId, redirect_uri: C.redirectUri,
        scope: "openid email profile", code_challenge_method: "S256", code_challenge: challenge, state,
      });
      location.assign(`${C.cognitoDomain}/oauth2/authorize?${q}`);
    },
    async token(params) {
      const res = await fetch(`${C.cognitoDomain}/oauth2/token`, {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ client_id: C.clientId, ...params }),
      });
      if (!res.ok) throw new Error("sign-in failed");
      const data = await res.json();
      sessionStorage.setItem("id_token", data.id_token);
      if (data.refresh_token) sessionStorage.setItem("refresh_token", data.refresh_token);
    },
    async handleCallback() {
      const q = new URLSearchParams(location.search);
      if (!q.has("code")) return;
      const verifier = sessionStorage.getItem("pkce_verifier");
      if (q.get("state") !== sessionStorage.getItem("pkce_state")) throw new Error("state mismatch");
      await this.token({ grant_type: "authorization_code", code: q.get("code"), redirect_uri: C.redirectUri, code_verifier: verifier });
      sessionStorage.removeItem("pkce_verifier");
      sessionStorage.removeItem("pkce_state");
      const back = sessionStorage.getItem("return_to") || "#/";
      history.replaceState(null, "", location.pathname + back);
    },
    async ensureFresh() {
      const c = this.claims();
      if (!c) return false;
      if (c.exp * 1000 - Date.now() > 5 * 60 * 1000) return true;
      const rt = sessionStorage.getItem("refresh_token");
      if (!rt) return false;
      try { await this.token({ grant_type: "refresh_token", refresh_token: rt }); return true; }
      catch { return false; }
    },
    logout() {
      sessionStorage.clear();
      location.assign(`${C.cognitoDomain}/logout?client_id=${C.clientId}&logout_uri=${encodeURIComponent(C.redirectUri)}`);
    },
  };

  // ------------------------------------------------------------------ API
  async function api(method, path, body) {
    if (!(await auth.ensureFresh())) { await auth.login(); throw new Error("redirecting to sign-in"); }
    const res = await fetch(C.apiBase + path, {
      method,
      headers: { Authorization: `Bearer ${auth.idToken}`, "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch { /* empty */ }
    if (res.status === 401) { await auth.login(); throw new Error("session expired"); }
    if (!res.ok) {
      const err = new Error((data && (data.error || data.message)) || `request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  // ------------------------------------------------------------------ shell / router
  function shell() {
    const role = auth.role();
    const c = auth.claims() || {};
    const links = {
      student: [["#/", "My exams & assignments"]],
      tutor: [["#/", "Exams"], ["#/assignments", "Assignments"], ["#/tutor/new-exam", "New exam"]],
      admin: [["#/", "Users"], ["#/schedules", "Exam schedules"], ["#/exams", "All exams"], ["#/assignments", "All assignments"]],
    }[role] || [];
    document.getElementById("nav").replaceChildren(
      ...links.map(([href, label]) => el("a", { href, class: location.hash === href || (!location.hash && href === "#/") ? "active" : "" }, label)),
    );
    document.getElementById("who").replaceChildren(
      el("span", {}, c["cognito:username"] || ""),
      role ? pill(role) : "",
      el("button", { class: "secondary", onclick: () => auth.logout() }, "Sign out"),
    );
  }

  let cleanup = null; // per-view teardown (timers, listeners)

  async function route() {
    if (cleanup) { cleanup(); cleanup = null; }
    if (!auth.idToken) return landing();
    shell();
    const role = auth.role();
    const hash = location.hash || "#/";
    const m = (re) => hash.match(re);
    let x;
    try {
      if (!role) return render(el("div", { class: "card" }, el("h1", {}, "No role assigned"),
        el("p", {}, "Your account is not in the students, tutors or admins group. Ask an administrator.")));
      if (role === "student") {
        if ((x = m(/^#\/exam\/([\w-]+)$/))) return await examView(x[1]);
        return await studentHome();
      }
      if ((x = m(/^#\/tutor\/exam\/([\w-]+)$/))) return await tutorExamView(x[1]);
      if ((x = m(/^#\/tutor\/assignment\/([\w-]+)$/))) return await submissionsView(x[1]);
      if (hash === "#/tutor/new-exam") return newExamView();
      if (hash === "#/assignments") return await assignmentsStaffView();
      if (role === "admin") {
        if (hash === "#/schedules") return await schedulesView();
        if (hash === "#/exams") return await examsStaffView();
        return await usersView();
      }
      return await examsStaffView();
    } catch (e) {
      render(el("div", { class: "card" }, el("h2", {}, "Something went wrong"), el("p", { class: "muted" }, e.message)));
    }
  }

  function landing() {
    document.getElementById("nav").replaceChildren();
    document.getElementById("who").replaceChildren();
    render(el("div", { class: "card hero" },
      el("h1", {}, "Online exams & assignment submissions"),
      el("p", { class: "muted" }, "Sit timed exams with automatic saving every 30 seconds, upload assignments up to 50 MB and get notified when results are released."),
      el("button", { onclick: () => auth.login() }, "Sign in")));
  }

  // ================================================================== STUDENT
  async function studentHome() {
    const [exams, assignments] = await Promise.all([api("GET", "/exams"), api("GET", "/assignments")]);
    const examRows = exams.map((e) => {
      let action;
      if (e.status === "results_released" && e.attempt_id) {
        action = pill(`Result: ${e.total_score ?? "—"} / ${e.max_score ?? "—"}`, "ok");
      } else if (e.attempt_status && e.attempt_status !== "in_progress") {
        action = pill("Submitted – awaiting results", "warn");
      } else if (e.is_open) {
        action = el("a", { class: "btn", href: `#/exam/${e.id}` }, e.attempt_id ? "Resume" : "Start exam");
      } else {
        action = pill("Not open");
      }
      return el("tr", {},
        el("td", {}, el("strong", {}, e.title), el("div", { class: "muted small" }, e.description || "")),
        el("td", {}, `${fmt(e.opens_at)} → ${fmt(e.closes_at)}`),
        el("td", {}, `${e.duration_minutes} min`),
        el("td", {}, action));
    });

    const asgRows = assignments.map((a) => {
      const bar = el("div", { class: "progress", hidden: true }, el("div"));
      const input = el("input", { type: "file", accept: ".pdf,.zip,application/pdf,application/zip" });
      const btn = el("button", { onclick: () => upload(a, input, bar, btn) }, "Upload");
      const status = a.submission_status
        ? pill(`${a.submission_status}: ${a.filename}`, { uploaded: "ok", pending: "warn", rejected: "bad" }[a.submission_status])
        : pill("Not submitted");
      return el("tr", {},
        el("td", {}, el("strong", {}, a.title), el("div", { class: "muted small" }, a.description || "")),
        el("td", {}, fmt(a.due_at)),
        el("td", {}, status),
        el("td", {}, el("div", { class: "row" }, input, btn), bar));
    });

    render(
      el("h1", {}, "My exams"),
      el("div", { class: "card table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Exam"), el("th", {}, "Window"), el("th", {}, "Duration"), el("th", {}, ""))),
        el("tbody", {}, examRows.length ? examRows : el("tr", {}, el("td", { colspan: 4, class: "muted" }, "No exams scheduled."))))),
      el("h1", {}, "Assignments"),
      el("div", { class: "card table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Assignment"), el("th", {}, "Due"), el("th", {}, "My submission"), el("th", {}, "Upload (PDF/ZIP ≤ 50 MB)"))),
        el("tbody", {}, asgRows.length ? asgRows : el("tr", {}, el("td", { colspan: 4, class: "muted" }, "No assignments."))))),
    );
  }

  async function upload(assignment, input, bar, btn) {
    const file = input.files[0];
    if (!file) return toast("Choose a PDF or ZIP file first", true);
    if (file.size > C.maxUploadMb * 1048576) return toast(`File is larger than ${C.maxUploadMb} MB`, true);
    btn.disabled = true;
    try {
      // 1) ask the API for a presigned POST  2) send the file straight to S3
      const { upload: post } = await api("POST", `/assignments/${assignment.id}/uploads`, { filename: file.name, size: file.size });
      const form = new FormData();
      Object.entries(post.fields).forEach(([k, v]) => form.append(k, v));
      form.append("file", file);
      bar.hidden = false;
      await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", post.url);
        xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) bar.firstChild.style.width = `${(ev.loaded / ev.total) * 100}%`; };
        xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`S3 rejected the upload (${xhr.status})`)));
        xhr.onerror = () => reject(new Error("network error during upload"));
        xhr.send(form);
      });
      toast(`Uploaded ${file.name} (${mb(file.size)}). Verifying – your tutor will be notified.`);
      setTimeout(route, 4000);
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  // ------------------------------------------------------------------ exam taking + autosave
  async function examView(examId) {
    const data = await api("POST", `/exams/${examId}/attempts`);
    const { attempt, questions } = data;
    const storeKey = `answers-${attempt.id}`;
    const clockOffset = new Date(attempt.server_time).getTime() - Date.now();
    const deadline = new Date(attempt.deadline_at).getTime();

    // Merge server answers with any local backup (written on every keystroke).
    let local = {};
    try { local = JSON.parse(localStorage.getItem(storeKey) || "{}"); } catch { /* ignore */ }
    const answers = { ...data.answers };
    const dirty = new Set();
    for (const [qid, v] of Object.entries(local)) {
      if (answers[qid] !== v) { answers[qid] = v; dirty.add(qid); }
    }

    const statusEl = el("span", { class: "muted small" }, dirty.size ? "Restored unsaved answers from this device" : "All answers saved");
    const timerEl = el("span", { class: "timer" }, "--:--");
    let saving = false;
    let submitted = false;

    const persistLocal = () => { try { localStorage.setItem(storeKey, JSON.stringify(answers)); } catch { /* quota */ } };
    const setAnswer = (qid, value) => { answers[qid] = value; dirty.add(qid); persistLocal(); statusEl.textContent = "Unsaved changes…"; };

    async function save() {
      if (saving || submitted || !dirty.size) return;
      saving = true;
      const batch = [...dirty];
      const payload = batch.map((qid) => ({ question_id: qid, response: answers[qid] }));
      const snapshot = Object.fromEntries(batch.map((q) => [q, answers[q]]));
      try {
        const r = await api("PUT", `/attempts/${attempt.id}/answers`, { answers: payload });
        batch.forEach((q) => { if (answers[q] === snapshot[q]) dirty.delete(q); });
        statusEl.textContent = `Saved ${r.saved} answer(s) at ${new Date(r.saved_at).toLocaleTimeString()}`;
      } catch (e) {
        statusEl.textContent = `Not saved (${e.message}) – kept on this device, retrying in ${C.autosaveSec}s`;
        if (e.status === 409) { submitted = true; toast(e.message, true); }
      } finally {
        saving = false;
      }
    }

    async function submit(auto = false) {
      if (submitted) return;
      if (!auto && !confirm("Submit your exam? You cannot change answers afterwards.")) return;
      submitted = true;
      try {
        const all = Object.entries(answers).map(([qid, response]) => ({ question_id: qid, response }));
        await api("POST", `/attempts/${attempt.id}/submit`, { answers: all });
        localStorage.removeItem(storeKey);
        toast(auto ? "Time is up – your exam was submitted automatically." : "Exam submitted. Good luck!");
        location.hash = "#/";
      } catch (e) {
        submitted = false;
        toast(`Submit failed: ${e.message}. Your answers are safe – try again.`, true);
      }
    }

    function tick() {
      const left = Math.max(0, deadline - (Date.now() + clockOffset));
      const s = Math.floor(left / 1000);
      timerEl.textContent = `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
      timerEl.classList.toggle("low", s < 300);
      if (left <= 0) submit(true);
    }

    const qNodes = questions.map((q, i) => {
      let input;
      if (q.kind === "mcq") {
        input = el("div", {}, ...(q.options || []).map((opt, idx) =>
          el("label", { class: "option" },
            el("input", { type: "radio", name: q.id, value: String(idx), checked: answers[q.id] === String(idx), onchange: () => setAnswer(q.id, String(idx)) }),
            opt)));
      } else {
        input = el("textarea", { value: answers[q.id] || "", oninput: (ev) => setAnswer(q.id, ev.target.value), maxlength: 10000 });
      }
      return el("div", { class: "card question" },
        el("div", { class: "row spread" }, el("div", { class: "prompt" }, `${i + 1}. ${q.prompt}`), pill(`${q.marks} mark${q.marks === 1 ? "" : "s"}`)),
        input);
    });

    render(
      el("div", { class: "exam-bar" },
        el("div", {}, el("strong", {}, attempt.title), el("div", {}, statusEl)),
        el("div", { class: "row" }, timerEl, el("button", { onclick: () => submit(false) }, "Submit exam"))),
      ...qNodes,
    );

    tick();
    const tickTimer = setInterval(tick, 1000);
    const saveTimer = setInterval(save, C.autosaveSec * 1000);
    const beforeUnload = (ev) => { if (dirty.size && !submitted) { ev.preventDefault(); ev.returnValue = ""; } };
    const onOnline = () => save();
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("online", onOnline);
    cleanup = () => {
      clearInterval(tickTimer); clearInterval(saveTimer);
      window.removeEventListener("beforeunload", beforeUnload);
      window.removeEventListener("online", onOnline);
      save();
    };
  }

  // ================================================================== TUTOR
  async function examsStaffView() {
    const exams = await api("GET", "/exams");
    const rows = exams.map((e) => el("tr", {},
      el("td", {}, el("strong", {}, e.title), auth.role() === "admin" ? el("div", { class: "muted small" }, e.created_by_email || "") : ""),
      el("td", {}, `${fmt(e.opens_at)} → ${fmt(e.closes_at)}`),
      el("td", {}, `${e.submitted} / ${e.attempts}`),
      el("td", {}, pill(e.status.replace("_", " "), e.status === "results_released" ? "ok" : "")),
      el("td", {}, el("div", { class: "row" },
        el("a", { class: "btn", href: `#/tutor/exam/${e.id}` }, "Attempts & marking"),
        e.status !== "results_released"
          ? el("button", { class: "secondary", onclick: () => release(e) }, "Release results") : ""))));
    render(
      el("div", { class: "row spread" }, el("h1", {}, "Exams"), el("a", { class: "btn", href: "#/tutor/new-exam" }, "+ New exam")),
      el("div", { class: "card table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Exam"), el("th", {}, "Window"), el("th", {}, "Submitted / started"), el("th", {}, "Status"), el("th", {}, ""))),
        el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: 5, class: "muted" }, "No exams yet."))))));
  }

  async function release(exam) {
    if (!confirm(`Release results for "${exam.title}" and email all students?`)) return;
    try {
      const r = await api("POST", `/exams/${exam.id}/release`);
      toast(`Results released. ${r.auto_submitted} timed-out attempt(s) auto-submitted. Emails are being sent.`);
      route();
    } catch (e) { toast(e.message, true); }
  }

  function newExamView() {
    const qList = el("div");
    const addQuestion = (kind) => {
      const optionsBox = el("div", { class: "field" });
      const block = el("div", { class: "card", "data-kind": kind },
        el("div", { class: "row spread" }, pill(kind === "mcq" ? "Multiple choice" : "Short answer"),
          el("button", { class: "secondary", onclick: () => block.remove() }, "Remove")),
        el("div", { class: "field" }, el("label", {}, "Question"), el("textarea", { name: "prompt", style: "min-height:60px" })),
        kind === "mcq" ? optionsBox : "",
        el("div", { class: "field" }, el("label", {}, "Marks"), el("input", { type: "number", name: "marks", value: kind === "mcq" ? 1 : 5, min: 0.5, step: 0.5 })));
      if (kind === "mcq") {
        optionsBox.append(el("label", {}, "Options (select the correct one)"));
        const name = `correct-${Math.random().toString(36).slice(2)}`;
        for (let i = 0; i < 4; i++) {
          optionsBox.append(el("div", { class: "row", style: "margin-bottom:6px" },
            el("input", { type: "radio", name, value: String(i), checked: i === 0 }),
            el("input", { type: "text", name: "option", placeholder: `Option ${i + 1}`, style: "flex:1" })));
        }
      }
      qList.append(block);
    };

    const title = el("input", { style: "width:100%" });
    const desc = el("input", { style: "width:100%" });
    const duration = el("input", { type: "number", value: 30, min: 1, max: 600 });
    const opens = el("input", { type: "datetime-local", value: toLocalInput(new Date().toISOString()) });
    const closes = el("input", { type: "datetime-local", value: toLocalInput(new Date(Date.now() + 7 * 864e5).toISOString()) });

    async function save() {
      const questions = [...qList.children].map((b) => {
        const kind = b.dataset.kind;
        const q = { kind, prompt: b.querySelector("[name=prompt]").value, marks: Number(b.querySelector("[name=marks]").value) };
        if (kind === "mcq") {
          const rows = [...b.querySelectorAll("input[name=option]")];
          const filled = rows.map((r, i) => ({ text: r.value.trim(), i })).filter((o) => o.text);
          const checked = Number(b.querySelector("input[type=radio]:checked").value);
          q.options = filled.map((o) => o.text);
          q.correct_option = filled.findIndex((o) => o.i === checked);
        }
        return q;
      });
      try {
        await api("POST", "/exams", {
          title: title.value, description: desc.value, duration_minutes: Number(duration.value),
          opens_at: fromLocalInput(opens.value), closes_at: fromLocalInput(closes.value), questions,
        });
        toast("Exam created");
        location.hash = auth.role() === "admin" ? "#/exams" : "#/";
      } catch (e) { toast(e.message, true); }
    }

    addQuestion("mcq");
    render(
      el("h1", {}, "New exam"),
      el("div", { class: "card" },
        el("div", { class: "field" }, el("label", {}, "Title"), title),
        el("div", { class: "field" }, el("label", {}, "Description"), desc),
        el("div", { class: "grid" },
          el("div", {}, el("label", {}, "Duration (minutes)"), duration),
          el("div", {}, el("label", {}, "Opens"), opens),
          el("div", {}, el("label", {}, "Closes"), closes))),
      qList,
      el("div", { class: "row" },
        el("button", { class: "secondary", onclick: () => addQuestion("mcq") }, "+ MCQ"),
        el("button", { class: "secondary", onclick: () => addQuestion("short") }, "+ Short answer"),
        el("button", { onclick: save }, "Create exam")));
  }

  async function tutorExamView(examId) {
    const { exam, short_questions: shortQs, attempts } = await api("GET", `/exams/${examId}/attempts`);
    const statusKind = { marked: "ok", auto_marked: "warn", submitted: "warn", in_progress: "" };
    const cards = attempts.map((a) => {
      const inputs = {};
      const markBlocks = shortQs.map((q) => {
        const ans = a.short_answers[q.id] || {};
        inputs[q.id] = el("input", { type: "number", min: 0, max: q.marks, step: 0.5, value: ans.mark ?? "", style: "width:90px" });
        return el("div", { class: "field" },
          el("label", {}, `Q${q.position}. ${q.prompt} (max ${q.marks})`),
          el("div", { class: "card", style: "background:#f8fafd;margin-bottom:6px;white-space:pre-wrap" }, ans.response || "(no answer)"),
          el("div", { class: "row" }, el("span", { class: "small muted" }, "Mark:"), inputs[q.id]));
      });
      const saveBtn = el("button", {
        onclick: async () => {
          const marks = Object.entries(inputs).filter(([, i]) => i.value !== "").map(([qid, i]) => ({ question_id: qid, mark: Number(i.value) }));
          try { await api("PUT", `/attempts/${a.id}/marks`, { marks }); toast(`Marks saved for ${a.student_name}`); route(); }
          catch (e) { toast(e.message, true); }
        },
        disabled: a.status === "in_progress",
      }, "Save marks");
      return el("div", { class: "card" },
        el("div", { class: "row spread" },
          el("div", {}, el("strong", {}, a.student_name), el("span", { class: "muted small" }, `  ${a.student_email || ""}`)),
          el("div", { class: "row" }, pill(a.status.replace("_", " "), statusKind[a.status]),
            el("span", {}, `MCQ ${a.mcq_score ?? "—"} + short ${a.short_score ?? "—"} = `, el("strong", {}, `${a.total_score ?? "—"} / ${a.max_score ?? "—"}`)))),
        el("div", { class: "muted small" }, `Submitted ${fmt(a.submitted_at)}`),
        shortQs.length ? el("div", { style: "margin-top:12px" }, ...markBlocks, saveBtn) : "");
    });
    render(
      el("div", { class: "row spread" }, el("h1", {}, exam.title), pill(exam.status.replace("_", " "))),
      el("p", { class: "muted" }, `${attempts.length} attempt(s). MCQs are auto-marked from the marking queue; mark short answers below, then release results from the Exams page.`),
      ...(cards.length ? cards : [el("div", { class: "card muted" }, "No attempts yet.")]));
  }

  async function assignmentsStaffView() {
    const list = await api("GET", "/assignments");
    const title = el("input", { style: "width:100%" });
    const desc = el("input", { style: "width:100%" });
    const due = el("input", { type: "datetime-local", value: toLocalInput(new Date(Date.now() + 14 * 864e5).toISOString()) });
    const rows = list.map((a) => el("tr", {},
      el("td", {}, el("strong", {}, a.title), el("div", { class: "muted small" }, a.description || "")),
      el("td", {}, fmt(a.due_at)),
      el("td", {}, String(a.submissions)),
      el("td", {}, el("a", { class: "btn", href: `#/tutor/assignment/${a.id}` }, "Submissions"))));
    render(
      el("h1", {}, "Assignments"),
      el("div", { class: "card table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Assignment"), el("th", {}, "Due"), el("th", {}, "Uploaded"), el("th", {}, ""))),
        el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: 4, class: "muted" }, "None yet."))))),
      el("div", { class: "card" }, el("h2", {}, "New assignment"),
        el("div", { class: "field" }, el("label", {}, "Title"), title),
        el("div", { class: "field" }, el("label", {}, "Instructions"), desc),
        el("div", { class: "field" }, el("label", {}, "Due"), due),
        el("button", {
          onclick: async () => {
            try { await api("POST", "/assignments", { title: title.value, description: desc.value, due_at: fromLocalInput(due.value) }); toast("Assignment created"); route(); }
            catch (e) { toast(e.message, true); }
          },
        }, "Create assignment")));
  }

  async function submissionsView(assignmentId) {
    const { assignment, submissions } = await api("GET", `/assignments/${assignmentId}/submissions`);
    const rows = submissions.map((s) => el("tr", {},
      el("td", {}, s.student_name, el("div", { class: "muted small" }, s.student_email || "")),
      el("td", {}, s.filename),
      el("td", {}, mb(s.size_bytes)),
      el("td", {}, fmt(s.uploaded_at)),
      el("td", {}, pill(s.status, s.status === "uploaded" ? "ok" : "bad")),
      el("td", {}, s.download_url ? el("a", { class: "btn", href: s.download_url }, "Download") : "")));
    render(
      el("h1", {}, `Submissions – ${assignment.title}`),
      el("div", { class: "card table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["Student", "File", "Size", "Uploaded", "Status", ""].map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: 6, class: "muted" }, "No submissions yet."))))));
  }

  // ================================================================== ADMIN
  async function usersView() {
    const users = await api("GET", "/admin/users");
    const username = el("input");
    const email = el("input", { type: "email" });
    const role = el("select", {}, ...["student", "tutor", "admin"].map((r) => el("option", { value: r }, r)));
    render(
      el("h1", {}, "Users"),
      el("div", { class: "card" }, el("h2", {}, "Create user"),
        el("p", { class: "muted small" }, "Cognito emails the user a temporary password; they set their own on first sign-in."),
        el("div", { class: "grid" },
          el("div", {}, el("label", {}, "Username"), username),
          el("div", {}, el("label", {}, "Email"), email),
          el("div", {}, el("label", {}, "Role"), role)),
        el("div", { style: "margin-top:12px" }, el("button", {
          onclick: async () => {
            try { await api("POST", "/admin/users", { username: username.value, email: email.value, role: role.value }); toast("User created and invited"); route(); }
            catch (e) { toast(e.message, true); }
          },
        }, "Create user"))),
      el("div", { class: "card table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["Username", "Email", "Role", "Status", "Created"].map((h) => el("th", {}, h)))),
        el("tbody", {}, users.map((u) => el("tr", {},
          el("td", {}, u.username), el("td", {}, u.email || ""), el("td", {}, u.role ? pill(u.role) : pill("none", "bad")),
          el("td", {}, pill(u.status, u.status === "CONFIRMED" ? "ok" : "warn")), el("td", {}, fmt(u.created))))))));
  }

  async function schedulesView() {
    const exams = await api("GET", "/exams");
    const rows = exams.map((e) => {
      const opens = el("input", { type: "datetime-local", value: toLocalInput(e.opens_at) });
      const closes = el("input", { type: "datetime-local", value: toLocalInput(e.closes_at) });
      const dur = el("input", { type: "number", value: e.duration_minutes, min: 1, max: 600, style: "width:80px" });
      return el("tr", {},
        el("td", {}, el("strong", {}, e.title), el("div", { class: "muted small" }, e.created_by_email || "")),
        el("td", {}, opens), el("td", {}, closes), el("td", {}, dur),
        el("td", {}, el("button", {
          onclick: async () => {
            try {
              await api("PATCH", `/exams/${e.id}/schedule`, { opens_at: fromLocalInput(opens.value), closes_at: fromLocalInput(closes.value), duration_minutes: Number(dur.value) });
              toast("Schedule saved");
            } catch (err) { toast(err.message, true); }
          },
        }, "Save")));
    });
    render(
      el("h1", {}, "Exam schedules"),
      el("div", { class: "card table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["Exam", "Opens", "Closes", "Minutes", ""].map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: 5, class: "muted" }, "No exams."))))));
  }

  // ------------------------------------------------------------------ boot
  window.addEventListener("hashchange", route);
  auth.handleCallback()
    .catch((e) => toast(`Sign-in failed: ${e.message}`, true))
    .finally(route);
})();
