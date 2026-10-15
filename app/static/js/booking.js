// Create-booking screen: every action goes through the JSON booking API.
(function () {
  const init = JSON.parse(document.getElementById("booking-init").textContent);
  const state = { patient: init.patient, slot: null, wantedSlotId: init.slotId };

  const $ = (id) => document.getElementById(id);
  const els = {
    selected: $("patient-selected"),
    picker: $("patient-picker"),
    search: $("patient-search"),
    results: $("patient-results"),
    newToggle: $("new-patient-toggle"),
    newForm: $("new-patient-form"),
    newAlert: $("new-patient-alert"),
    slots: $("slots"),
    slotSummary: $("slot-summary"),
    alert: $("booking-alert"),
    summary: $("booking-summary"),
    submit: $("booking-submit"),
  };

  async function api(url, options) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (_) {
      throw new Error("Could not reach the server. Please check your connection and try again.");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.message || "Something went wrong. Please try again.");
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  const postJson = (url, body) =>
    api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  function el(tag, props, ...children) {
    const node = Object.assign(document.createElement(tag), props || {});
    node.append(...children);
    return node;
  }

  function showAlert(node, message) {
    node.textContent = message || "";
    node.hidden = !message;
  }

  const checked = (name) => document.querySelector(`input[name="${name}"]:checked`);
  const labelFor = (name) => checked(name).closest("label");

  // --- Patient -------------------------------------------------------------
  function demoTag(record) {
    return record.is_demo ? el("span", { className: "tag tag-demo", textContent: "Demo" }) : "";
  }

  function patientLine(patient) {
    return el(
      "div",
      null,
      el("div", { className: "appt-patient" }, patient.name + " ", demoTag(patient)),
      el("div", { className: "muted", textContent: patient.mobile + (patient.email ? " · " + patient.email : "") })
    );
  }

  function selectPatient(patient) {
    state.patient = patient;
    els.selected.replaceChildren();
    if (patient) {
      const change = el("button", { className: "btn btn-sm", type: "button", textContent: "Change" });
      change.addEventListener("click", () => selectPatient(null));
      els.selected.append(patientLine(patient), change);
    }
    els.selected.hidden = !patient;
    els.picker.hidden = !!patient;
    if (!patient) els.search.focus();
    refreshSummary();
  }

  function renderResults(patients, query) {
    els.results.replaceChildren();
    if (!patients.length) {
      if (query) {
        els.results.append(
          el("li", null, el("span", { className: "muted", textContent: "No matching patient. Use “New patient” to register them." }))
        );
      }
      return;
    }
    for (const patient of patients) {
      const pick = el("button", { className: "btn btn-sm", type: "button", textContent: "Select" });
      pick.addEventListener("click", () => selectPatient(patient));
      els.results.append(el("li", null, patientLine(patient), pick));
    }
  }

  let searchTimer;
  let searchSeq = 0;
  async function runSearch() {
    const query = els.search.value.trim();
    const seq = ++searchSeq;
    try {
      const patients = await api("/api/patients?q=" + encodeURIComponent(query));
      if (seq === searchSeq) renderResults(patients, query);
    } catch (_) {
      /* keep the previous results on a failed search */
    }
  }
  els.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 200);
  });

  els.newToggle.addEventListener("click", () => {
    els.newForm.hidden = !els.newForm.hidden;
    if (!els.newForm.hidden) {
      const typed = els.search.value.trim();
      const field = /^[\d\s+()-]+$/.test(typed) ? "mobile" : "name";
      if (typed && !els.newForm.elements[field].value) els.newForm.elements[field].value = typed;
      els.newForm.elements.name.focus();
    }
  });

  els.newForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    showAlert(els.newAlert, "");
    const body = Object.fromEntries(new FormData(els.newForm));
    try {
      const patient = await postJson("/api/patients", body);
      els.newForm.reset();
      els.newForm.hidden = true;
      selectPatient(patient);
    } catch (error) {
      showAlert(els.newAlert, error.message);
      const existing = error.data && error.data.patient;
      if (existing) {
        const use = el("button", { className: "btn btn-sm", type: "button", textContent: "Use this patient" });
        use.addEventListener("click", () => {
          els.newForm.hidden = true;
          showAlert(els.newAlert, "");
          selectPatient(existing);
        });
        els.newAlert.append(" ", use);
      }
    }
  });

  // --- Slots ---------------------------------------------------------------
  function selectSlot(slot, button) {
    state.slot = slot;
    for (const node of els.slots.querySelectorAll(".is-selected")) {
      node.classList.remove("is-selected");
      node.setAttribute("aria-pressed", "false");
    }
    if (button) {
      button.classList.add("is-selected");
      button.setAttribute("aria-pressed", "true");
    }
    refreshSummary();
  }

  let slotSeq = 0;
  async function loadSlots() {
    const seq = ++slotSeq;
    selectSlot(null);
    const doctorId = checked("doctor").value;
    const day = checked("date").value;
    let slots;
    try {
      slots = await api(`/api/doctors/${doctorId}/slots?date=${day}`);
    } catch (error) {
      if (seq === slotSeq) els.slots.replaceChildren(el("p", { className: "empty", textContent: error.message }));
      return;
    }
    if (seq !== slotSeq) return;

    els.slots.replaceChildren();
    const open = slots.filter((s) => s.available).length;
    els.slotSummary.textContent = slots.length ? `${open} of ${slots.length} available` : "";
    if (!slots.length) {
      els.slots.append(el("p", { className: "empty", textContent: "No consultation slots for this doctor on this day." }));
      return;
    }
    for (const slot of slots) {
      const note = { AVAILABLE: "Available", BOOKED: "Booked", BLOCKED: "Doctor unavailable", PAST: "Past" }[slot.status] || "Unavailable";
      const button = el(
        "button",
        { type: "button", className: "slot" + (slot.available ? "" : slot.status === "BOOKED" || slot.status === "BLOCKED" ? " is-unavailable is-booked" : " is-unavailable is-past"), disabled: !slot.available },
        el("strong", { textContent: slot.start_label }),
        el("span", { textContent: `${slot.duration_minutes} min · ${note}` })
      );
      if (slot.available) {
        button.addEventListener("click", () => selectSlot(slot, button));
        if (slot.id === state.wantedSlotId) selectSlot(slot, button);
      }
      els.slots.append(button);
    }
    state.wantedSlotId = null;
  }

  for (const input of document.querySelectorAll('input[name="doctor"], input[name="date"]')) {
    input.addEventListener("change", () => {
      showAlert(els.alert, "");
      loadSlots();
    });
  }

  // --- Submit --------------------------------------------------------------
  function refreshSummary() {
    const ready = !!(state.patient && state.slot);
    els.submit.disabled = !ready;
    if (ready) {
      const doctor = labelFor("doctor").querySelector("strong").textContent;
      const day = labelFor("date").textContent.trim();
      els.summary.textContent = `${state.patient.name} with ${doctor} · ${day} at ${state.slot.start_label} (${state.slot.duration_minutes} min)`;
    } else if (!state.patient) {
      els.summary.textContent = state.slot ? "Choose a patient to continue." : "Choose a patient and a time slot to continue.";
    } else {
      els.summary.textContent = "Choose a time slot to continue.";
    }
  }

  els.submit.addEventListener("click", async () => {
    if (!state.patient || !state.slot) return;
    showAlert(els.alert, "");
    els.submit.disabled = true;
    try {
      const appointment = await postJson("/api/appointments", {
        patient_id: state.patient.id,
        slot_id: state.slot.id,
        service_id: Number($("service").value),
        reason: $("reason").value,
        source: $("source").value,
      });
      window.location.href = "/?booked=" + appointment.id;
    } catch (error) {
      showAlert(els.alert, error.message);
      // Slot was taken or has passed: show the latest availability so staff can pick again.
      await loadSlots();
    }
  });

  selectPatient(state.patient);
  runSearch();
  loadSlots();
})();
