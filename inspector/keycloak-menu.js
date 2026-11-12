const accountLink = document.querySelector("[data-account-link]");
if (accountLink) {
  fetch("/auth/status", { cache: "no-store", credentials: "same-origin" })
    .then(response => { accountLink.hidden = response.status !== 204; })
    .catch(() => {});
}
