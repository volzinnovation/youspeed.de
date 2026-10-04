const search = document.getElementById("sign-search");
const count = document.querySelector(".reference-count");
const signs = Array.from(document.querySelectorAll(".reference-sign"));
search?.addEventListener("input", () => {
  const words = search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  let visible = 0;
  for (const sign of signs) {
    sign.hidden = !words.every((word) => sign.dataset.search.includes(word));
    if (!sign.hidden) visible++;
  }
  count.textContent = `${visible} ${count.dataset.countLabel}`;
});
