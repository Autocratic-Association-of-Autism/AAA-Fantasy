/* Editorial artwork placement for the Week 5 recap only. */
(() => {
  if (!window.location.pathname.endsWith("/ledger/2026-week5-weekly-recap.html")) return;

  const article = document.querySelector("article.editable-ledger");
  if (!article) return;

  const gallery = article.querySelector(".recap-art-pair");
  const opposition = gallery?.querySelector("figure.recap-art");
  const oppositionImage = opposition?.querySelector("img");
  const chanceSection = article.querySelector("#week5-chance-zak");
  if (!gallery || !opposition || !oppositionImage || !chanceSection) return;

  // Place the opposition poster beside the opening Chance paragraphs.
  let openingParagraph = chanceSection.nextElementSibling;
  while (openingParagraph && openingParagraph.tagName !== "P") {
    openingParagraph = openingParagraph.nextElementSibling;
  }
  if (!openingParagraph) return;

  opposition.classList.add("recap-art-float-right", "recap-art-campaign");
  if (!oppositionImage.closest("a")) {
    const viewPoster = document.createElement("a");
    viewPoster.href = oppositionImage.src;
    viewPoster.target = "_blank";
    viewPoster.rel = "noopener noreferrer";
    viewPoster.title = "View opposition poster at full size";
    oppositionImage.replaceWith(viewPoster);
    viewPoster.appendChild(oppositionImage);
  }
  openingParagraph.after(opposition);

  // Use the uploaded filename for the separate campaign-integrity graphic.
  const auditURL = oppositionImage.src.replace(
    "chance-robinson-opposition-poster.png",
    "chance-robinson-campaign-under-review.png"
  );
  const auditFigure = document.createElement("figure");
  auditFigure.className = "recap-art recap-art-float-left recap-art-campaign";
  const auditLink = document.createElement("a");
  auditLink.href = auditURL;
  auditLink.target = "_blank";
  auditLink.rel = "noopener noreferrer";
  auditLink.title = "View campaign audit at full size";
  const auditImage = document.createElement("img");
  auditImage.src = auditURL;
  auditImage.alt = "Satirical campaign audit poster about Chance Robinson's integrity campaign";
  auditImage.loading = "lazy";
  const auditCaption = document.createElement("figcaption");
  auditCaption.textContent = "Integrity: a central theme of Chance's campaign materials.";
  auditLink.appendChild(auditImage);
  auditFigure.append(auditLink, auditCaption);

  // The two posters now flow with separate portions of the story.
  const betweenPosters = document.createElement("div");
  betweenPosters.className = "recap-clear";
  gallery.replaceWith(betweenPosters, auditFigure);

  // Prevent the second image from crossing into the next matchup.
  const nextSection = article.querySelector("#week5-macon-louis");
  if (nextSection) {
    const sectionDivider = nextSection.previousElementSibling;
    const finalClear = document.createElement("div");
    finalClear.className = "recap-clear";
    (sectionDivider?.tagName === "HR" ? sectionDivider : nextSection).before(finalClear);
  }
})();
