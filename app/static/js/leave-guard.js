// "Back to dashboard" for the assistant and call demo. With no active conversation the link
// simply navigates. During one, it asks first; leaving runs the page's own end flow, then opens
// the dashboard. Every link marked data-leave-guard is covered.
window.LeaveGuard = function ({ isActive, beforeLeave }) {
  const dialog = document.getElementById("leave-dialog");
  const stay = dialog.querySelector("[data-stay]");
  const leave = dialog.querySelector("[data-leave]");
  let target = "/";

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-leave-guard]");
    // Opening in a new tab leaves this conversation running, so it needs no question.
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (!isActive()) return;
    event.preventDefault();
    target = link.getAttribute("href") || "/";
    dialog.showModal();
    stay.focus();
  });
  stay.addEventListener("click", () => dialog.close());
  leave.addEventListener("click", async () => {
    leave.disabled = stay.disabled = true;
    try {
      await beforeLeave();
    } finally {
      window.location.assign(target);
    }
  });
};
