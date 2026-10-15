// Staff pages: small, dependable interaction helpers. Everything works without this
// file; it only adds confirmation, double-submit protection, feedback near the
// action, remembered menu groups and the mobile menu drawer.
(function () {
  const store = {
    get(key, fallback) {
      try {
        const value = window.localStorage.getItem(key);
        return value === null ? fallback : JSON.parse(value);
      } catch (_) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
      } catch (_) {
        /* private mode or storage disabled: the menu simply starts expanded */
      }
    },
  };
  const session = {
    take(key) {
      try {
        const value = window.sessionStorage.getItem(key);
        window.sessionStorage.removeItem(key);
        return value ? JSON.parse(value) : null;
      } catch (_) {
        return null;
      }
    },
    put(key, value) {
      try {
        window.sessionStorage.setItem(key, JSON.stringify(value));
      } catch (_) {
        /* feedback falls back to the notice at the top of the page */
      }
    },
  };

  // --- Forms: confirm irreversible actions, never submit twice, show progress ----------------
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.dataset.submitting === "1") {
      event.preventDefault(); // a second click while the first submit is on its way
      return;
    }
    // A confirmation can sit on the form, or on one button when only that button is irreversible.
    const message = (event.submitter && event.submitter.dataset.confirm) || form.dataset.confirm;
    if (message && !window.confirm(message)) {
      event.preventDefault();
      return;
    }
    if (event.defaultPrevented) return;
    form.dataset.submitting = "1";
    form.setAttribute("aria-busy", "true");
    const button = event.submitter || form.querySelector("button[type=submit], button:not([type])");
    if (button) button.classList.add("is-loading");
    // The buttons are not disabled (a disabled submit button would drop its name/value from the post);
    // they are marked busy instead, and further submits are ignored above.
    for (const other of form.querySelectorAll("button")) other.setAttribute("aria-disabled", "true");
    // Remember where the action happened, so the result can be shown there after the page reloads.
    const anchor = form.closest("[id]");
    if (anchor && form.method.toLowerCase() === "post") {
      session.put("lastAction", { path: window.location.pathname, anchor: anchor.id, at: Date.now() });
    }
  });

  // Coming back with the browser's Back button must not leave buttons stuck in "busy".
  window.addEventListener("pageshow", () => {
    for (const form of document.querySelectorAll("form[data-submitting]")) {
      delete form.dataset.submitting;
      form.removeAttribute("aria-busy");
      for (const button of form.querySelectorAll("button")) {
        button.classList.remove("is-loading");
        button.removeAttribute("aria-disabled");
      }
    }
  });

  // --- Feedback next to the action ---------------------------------------------------------------
  // After a post-and-redirect, bring the item that was acted on back into view and show the result
  // beside it, instead of leaving the only confirmation at the top of a long page.
  const last = session.take("lastAction");
  const notice = document.getElementById("page-notice");
  if (last && notice && Date.now() - last.at < 20000 && !window.location.hash) {
    const target = document.getElementById(last.anchor);
    if (target && target.getBoundingClientRect().top > window.innerHeight * 0.6) {
      target.classList.add("just-updated");
      target.scrollIntoView({ block: "center" });
      const toast = notice.cloneNode(true);
      toast.removeAttribute("id");
      toast.classList.add("toast");
      document.body.appendChild(toast);
      window.setTimeout(() => toast.classList.add("is-leaving"), 5000);
      window.setTimeout(() => toast.remove(), 5400);
    }
  }

  // --- "More actions" menus: one open at a time, close on Escape or an outside click -------------
  const menus = () => document.querySelectorAll("details.more-menu[open]");
  document.addEventListener("click", (event) => {
    for (const menu of menus()) if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    for (const menu of menus()) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
    closeDrawer();
  });

  // --- Navigation: remembered groups and the mobile drawer -----------------------------------------
  const groups = store.get("navGroups", {});
  for (const group of document.querySelectorAll("details.nav-group")) {
    const key = group.dataset.group;
    // The group holding the current page always stays open so the active page is visible.
    if (groups[key] === false && !group.classList.contains("has-active")) group.open = false;
    group.addEventListener("toggle", () => {
      const state = store.get("navGroups", {});
      state[key] = group.open;
      store.set("navGroups", state);
    });
  }

  const toggle = document.querySelector(".menu-toggle");
  const nav = document.getElementById("site-nav");
  function closeDrawer() {
    if (!toggle || !document.body.classList.contains("nav-open")) return;
    document.body.classList.remove("nav-open");
    toggle.setAttribute("aria-expanded", "false");
  }
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = !document.body.classList.contains("nav-open");
      document.body.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      if (open) (nav.querySelector("[aria-current=page]") || nav.querySelector("a")).focus({ preventScroll: true });
    });
    nav.addEventListener("click", (event) => {
      if (event.target.closest("a")) closeDrawer();
    });
  }
})();
