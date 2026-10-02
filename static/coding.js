const search = document.getElementById("problem-search");
const cards = [...document.querySelectorAll(".catalog-card")];
const empty = document.getElementById("empty-state");
let activeFilter = "All";

function filterCards() {
  const query = search.value.toLowerCase().trim();
  let visible = 0;
  cards.forEach((card) => {
    const matchesText = card.dataset.title.includes(query);
    const matchesDifficulty = activeFilter === "All" || card.dataset.difficulty === activeFilter;
    const show = matchesText && matchesDifficulty;
    card.classList.toggle("is-hidden", !show);
    if (show) visible += 1;
  });
  empty.classList.toggle("hidden", visible !== 0);
}

search.addEventListener("input", filterCards);
document.querySelectorAll(".filter-btn").forEach((button) => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    document.querySelectorAll(".filter-btn").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    filterCards();
  });
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    search.focus();
  }
});
